from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone as dt_timezone
from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, TestCase

from hr_assessment.api.views_assessment import annual_case_list, finalize_case
from hr_assessment.models.case import HrAnnualAssessmentCase
from hr_assessment.models.cycle import HrAssessmentCycle
from hr_assessment.models.result import HrAssessmentDecisionSession


class Hr12AnnualApiTests(TestCase):
    tenant_id = 77

    def setUp(self):
        self.factory = RequestFactory()
        self.user = SimpleNamespace(
            is_authenticated=True,
            is_superuser=True,
            has_perm=lambda _code: True,
        )
        self.policy_id = uuid.uuid4()
        self.cycle = HrAssessmentCycle.objects.create(
            tenant_id=self.tenant_id,
            cycle_no="2026-ANNUAL",
            assessment_type="ANNUAL",
            name="2026 年度考核",
            business_year=2026,
            start_at=datetime(2026, 1, 1, tzinfo=dt_timezone.utc),
            end_at=datetime(2026, 12, 31, 23, 59, tzinfo=dt_timezone.utc),
            policy_version_id=self.policy_id,
            lifecycle_status="ACTIVE",
        )
        self.case = HrAnnualAssessmentCase.objects.create(
            tenant_id=self.tenant_id,
            assessment_type="ANNUAL",
            cycle=self.cycle,
            staff_id=uuid.uuid4(),
            policy_version_id=self.policy_id,
            status="PROPOSED",
            business_year=2026,
        )

    def _get(self, path: str, *, tenant_id=None):
        request = self.factory.get(path)
        request.user = self.user
        request.tenant_id = tenant_id or self.tenant_id
        return request

    def _post(self, path: str, body: dict, *, tenant_id=None):
        request = self.factory.post(
            path,
            data=json.dumps(body),
            content_type="application/json",
        )
        request.user = self.user
        request.tenant_id = tenant_id or self.tenant_id
        return request

    def test_annual_list_is_tenant_scoped_and_exposes_completed_decision(self):
        other_cycle = HrAssessmentCycle.objects.create(
            tenant_id=88,
            cycle_no="2026-ANNUAL",
            assessment_type="ANNUAL",
            name="其它学校年度考核",
            business_year=2026,
            start_at=datetime(2026, 1, 1, tzinfo=dt_timezone.utc),
            end_at=datetime(2026, 12, 31, 23, 59, tzinfo=dt_timezone.utc),
            policy_version_id=uuid.uuid4(),
            lifecycle_status="ACTIVE",
        )
        HrAnnualAssessmentCase.objects.create(
            tenant_id=88,
            assessment_type="ANNUAL",
            cycle=other_cycle,
            staff_id=uuid.uuid4(),
            policy_version_id=other_cycle.policy_version_id,
            status="PROPOSED",
            business_year=2026,
        )
        decision = HrAssessmentDecisionSession.objects.create(
            tenant_id=self.tenant_id,
            cycle_id=self.cycle.id,
            status="COMPLETED",
            case_refs_json=[str(self.case.id)],
        )

        response = annual_case_list(self._get("/api/v1/hr/assessments/annual"))
        self.assertEqual(response.status_code, 200)
        rows = json.loads(response.content)["data"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], str(self.case.id))
        self.assertEqual(rows[0]["decisionSessionId"], str(decision.id))
        self.assertFalse(rows[0]["providerSnapshotReady"])

    @patch("hr_assessment.api.views_assessment.AssessmentFinalizationService.finalize")
    def test_finalize_endpoint_uses_formal_service_boundary(self, finalize):
        result = SimpleNamespace(
            id=uuid.uuid4(),
            case_id=self.case.id,
            status="FINALIZED",
            grade_code="QUALIFIED",
            display_grade_snapshot_json={"zh-CN": "合格"},
            calculated_score=None,
            decision_reason="年度考核工作台正式审定",
            decision_session_id=uuid.uuid4(),
            finalized_at=None,
            finalized_by=None,
            result_version_no=1,
            content_hash="a" * 64,
        )
        finalize.return_value = result
        decision_id = str(result.decision_session_id)

        response = finalize_case(
            self._post(
                f"/api/v1/hr/assessments/cases/{self.case.id}/finalize",
                {
                    "gradeCode": "QUALIFIED",
                    "decisionSessionId": decision_id,
                    "decisionReason": "年度考核工作台正式审定",
                },
            ),
            self.case.id,
        )
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content)["data"]
        self.assertEqual(payload["caseId"], str(self.case.id))
        self.assertEqual(payload["result"]["gradeCode"], "QUALIFIED")
        args = finalize.call_args.kwargs
        self.assertEqual(args["case_id"], self.case.id)
        self.assertEqual(args["payload"].grade_code, "QUALIFIED")
        self.assertEqual(str(args["payload"].decision_session_id), decision_id)

    def test_finalize_rejects_unknown_grade_before_formal_write(self):
        response = finalize_case(
            self._post(
                f"/api/v1/hr/assessments/cases/{self.case.id}/finalize",
                {"gradeCode": "FAKE_GREEN", "decisionSessionId": str(uuid.uuid4())},
            ),
            self.case.id,
        )
        self.assertEqual(response.status_code, 400)
        payload = json.loads(response.content)
        self.assertEqual(payload["error"]["code"], "ASSESSMENT_GRADE_INVALID")
