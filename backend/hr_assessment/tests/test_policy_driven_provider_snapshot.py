from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone as dt_timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, TestCase

from hr_assessment.api.views_assessment import eligibility_probe
from hr_assessment.models.case import HrAssessmentCase
from hr_assessment.models.cycle import HrAssessmentCycle
from hr_assessment.models.policy import (
    HrAssessmentPolicyPack,
    HrAssessmentPolicyVersion,
    HrEvidenceRequirement,
    HrIndicatorBinding,
    HrIndicatorDefinition,
    HrIndicatorSetVersion,
    HrIndicatorVersion,
)
from hr_assessment.providers.base import ProviderResult, ProviderStatus
from hr_assessment.service.evidence import (
    EvidenceSnapshotError,
    PolicyEvidenceResolver,
    ProviderCollectionOrchestrator,
    ProviderEvidenceSnapshotService,
)
from hr_assessment.services.finalization_service import AssessmentFinalizationService


class _AlwaysOkOrchestrator:
    def __init__(self):
        self.providers = {
            "person": object(),
            "development": object(),
            "time_summary": object(),
        }

    def collect_one(self, tenant_id, staff_id, provider_name, **kwargs):
        return ProviderResult(
            status=ProviderStatus.OK,
            data=[{"staffId": str(staff_id), "provider": provider_name}],
            source_version=f"test-{provider_name}-v1",
        )


class PolicyDrivenProviderSnapshotTests(TestCase):
    tenant_id = 77

    def setUp(self):
        self.indicator_set = HrIndicatorSetVersion.objects.create(
            tenant_id=self.tenant_id,
            name="2026 年度正式指标集",
            version_no=1,
            status="PUBLISHED",
            total_weight=Decimal("1.00"),
        )
        self.policy_pack = HrAssessmentPolicyPack.objects.create(
            tenant_id=self.tenant_id,
            code="ANNUAL-2026",
            name="2026 年度考核政策",
            assessment_domain="ANNUAL",
        )
        self.policy = HrAssessmentPolicyVersion.objects.create(
            tenant_id=self.tenant_id,
            policy_pack=self.policy_pack,
            version_no=1,
            status="PUBLISHED",
            effective_from="2026-01-01",
            assessment_types=["ANNUAL"],
            rating_scale_version_id=uuid.uuid4(),
            indicator_set_version_id=self.indicator_set.id,
            workflow_version_id=uuid.uuid4(),
        )
        self.cycle = HrAssessmentCycle.objects.create(
            tenant_id=self.tenant_id,
            cycle_no="2026-ANNUAL",
            assessment_type="ANNUAL",
            name="2026 年度考核",
            start_at=datetime(2026, 1, 1, tzinfo=dt_timezone.utc),
            end_at=datetime(2026, 12, 31, 23, 59, tzinfo=dt_timezone.utc),
            policy_version_id=self.policy.id,
            lifecycle_status="ACTIVE",
        )
        self.case = HrAssessmentCase.objects.create(
            tenant_id=self.tenant_id,
            assessment_type="ANNUAL",
            cycle=self.cycle,
            staff_id=uuid.uuid4(),
            policy_version_id=self.policy.id,
            status="PROPOSED",
        )

    def _bind_indicator(
        self,
        *,
        code: str,
        source_provider: str,
        accepted_provider_types: list[str] | None = None,
        document_required: bool = False,
    ) -> HrIndicatorVersion:
        definition = HrIndicatorDefinition.objects.create(
            tenant_id=self.tenant_id,
            code=code,
            name=code,
            dimension="PERFORMANCE",
        )
        version = HrIndicatorVersion.objects.create(
            tenant_id=self.tenant_id,
            indicator=definition,
            version_no=1,
            status="PUBLISHED",
            name=code,
            dimension="PERFORMANCE",
            value_type="NUMBER",
            source_provider=source_provider,
            valid_from="2026-01-01",
        )
        HrIndicatorBinding.objects.create(
            id=uuid.uuid4(),
            indicator_set=self.indicator_set,
            indicator_version=version,
            weight=Decimal("0.5000"),
            required=True,
        )
        if accepted_provider_types is not None or document_required:
            HrEvidenceRequirement.objects.create(
                id=uuid.uuid4(),
                indicator_version=version,
                accepted_provider_types=accepted_provider_types or [],
                document_required=document_required,
            )
        return version

    def test_policy_resolver_derives_required_providers_from_exact_indicator_set(self):
        self._bind_indicator(
            code="DEV",
            source_provider="HR10_DEVELOPMENT",
            accepted_provider_types=["HR10_DEVELOPMENT"],
        )
        self._bind_indicator(
            code="TIME",
            source_provider="HR11_TIME",
            accepted_provider_types=["HR11_TIME"],
        )

        plan = PolicyEvidenceResolver(self.tenant_id).resolve_case(self.case.id)

        self.assertEqual(
            plan.required_providers,
            ("development", "person", "time_summary"),
        )
        self.assertEqual(plan.as_of, self.cycle.end_at)
        self.assertEqual(plan.authority["policyVersionId"], str(self.policy.id))
        self.assertEqual(
            plan.authority["indicatorSetVersionId"],
            str(self.indicator_set.id),
        )
        self.assertEqual(plan.authority["asOfBasis"], "CYCLE_END_AT")

    def test_unknown_required_source_is_fail_closed(self):
        self._bind_indicator(code="BAD", source_provider="SILENT_FAKE_SOURCE")

        with self.assertRaises(EvidenceSnapshotError) as cm:
            PolicyEvidenceResolver(self.tenant_id).resolve_case(self.case.id)

        self.assertEqual(cm.exception.code, "ASSESSMENT_PROVIDER_MAPPING_UNKNOWN")

    def test_human_review_source_is_recorded_but_not_faked_as_provider(self):
        self._bind_indicator(
            code="REVIEW",
            source_provider="REVIEWER",
            accepted_provider_types=["REVIEWER"],
        )

        plan = PolicyEvidenceResolver(self.tenant_id).resolve_case(self.case.id)

        self.assertEqual(plan.required_providers, ("person",))
        self.assertEqual(
            plan.authority["indicatorProviders"][0]["sourceKind"],
            "WORKFLOW",
        )

    def test_policy_capture_freezes_authority_and_satisfies_finalization_snapshot_gate(self):
        self._bind_indicator(
            code="DEV",
            source_provider="HR10_DEVELOPMENT",
            accepted_provider_types=["HR10_DEVELOPMENT"],
        )
        service = ProviderEvidenceSnapshotService(
            self.tenant_id,
            orchestrator=_AlwaysOkOrchestrator(),
        )

        snapshot = service.capture_case_from_policy(
            case_id=self.case.id,
            request_id="policy-capture-001",
        )

        self.case.refresh_from_db()
        self.assertEqual(snapshot.status, "READY")
        self.assertEqual(snapshot.as_of, self.cycle.end_at)
        self.assertEqual(snapshot.required_providers_json, ["development", "person"])
        self.assertEqual(snapshot.authority_json["policyVersionId"], str(self.policy.id))
        self.assertEqual(self.case.provider_snapshot_set_id, snapshot.id)
        self.assertEqual(
            AssessmentFinalizationService(self.tenant_id)._provider_snapshot_blockers(
                case=self.case
            ),
            [],
        )

        snapshot.authority_json = {}
        with self.assertRaisesRegex(
            ValueError,
            "HR12_PROVIDER_SNAPSHOT_SET_IMMUTABLE",
        ):
            snapshot.save(update_fields=["authority_json", "updated_at"])
        snapshot.refresh_from_db()
        self.assertTrue(snapshot.authority_json)
        self.assertEqual(
            AssessmentFinalizationService(self.tenant_id)._provider_snapshot_blockers(
                case=self.case
            ),
            [],
        )

    def test_capability_probe_reports_connector_capability_not_empty_id_health(self):
        status = ProviderCollectionOrchestrator().capability_status()
        self.assertEqual(status["hr10"], "OK")
        self.assertEqual(status["hr11"], "OK")
        self.assertEqual(status["academic"], "UNAVAILABLE")

        request = RequestFactory().get("/api/v1/hr/assessments/eligibility")
        request.user = SimpleNamespace(is_authenticated=True, is_superuser=True)
        with patch(
            "hr_assessment.api.views_assessment.resolve_tenant_from_assignment",
            return_value=self.tenant_id,
        ):
            response = eligibility_probe(request)
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content)["data"]
        self.assertEqual(payload["scope"], "CAPABILITY")
        self.assertEqual(payload["providerStatus"]["hr10"], "OK")
