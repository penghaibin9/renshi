"""P0 contracts for sealed HR09 final decisions and frozen evidence."""

import json
import uuid
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.test import RequestFactory, SimpleTestCase
from django.utils import timezone

from hr_qualification.api import views_review
from hr_qualification.models import (
    HrDoubleTeacherEvidenceItem,
    HrDoubleTeacherEvidencePackage,
    HrDoubleTeacherFinalDecision,
    HrDoubleTeacherFinalDecisionAmendment,
)
from hr_qualification.models.review import (
    FinalDecisionAmendmentQuerySet,
    FinalDecisionQuerySet,
)
from hr_qualification.providers.base import ProviderEvidenceResult
from hr_qualification.services.final_decision_authority_service import (
    FINAL_DECISION_CORRECT_PERMISSION,
    FINAL_DECISION_REVOKE_PERMISSION,
    FinalDecisionAuthorityService,
)


class FinalDecisionSealContractTests(SimpleTestCase):
    def _decision(self):
        return HrDoubleTeacherFinalDecision(
            application_id_id=uuid.uuid4(),
            decision="RECOGNIZE",
            recognized_level="DOUBLE_TEACHER_JUNIOR",
            effective_from=date(2026, 9, 1),
            decision_authority="School committee",
            meeting_ref="MEETING-2026-09",
            published_at=timezone.now(),
        )

    def test_seal_covers_authority_and_is_verifiable(self):
        decision = self._decision()
        with patch.object(HrDoubleTeacherFinalDecision, "save", autospec=True):
            FinalDecisionAuthorityService.seal_initial(
                decision,
                actor_user_id=88,
            )
        self.assertTrue(decision.verify_content_hash())
        self.assertEqual(decision.published_by, 88)
        self.assertEqual(
            decision.authority_receipt_json["permissionCode"],
            "hr.qualification.review.finalize",
        )

    def test_queryset_and_bulk_bypasses_are_closed(self):
        decision_qs = FinalDecisionQuerySet(
            model=HrDoubleTeacherFinalDecision,
            using="default",
        )
        amendment_qs = FinalDecisionAmendmentQuerySet(
            model=HrDoubleTeacherFinalDecisionAmendment,
            using="default",
        )
        for operation in (
            lambda: decision_qs.update(decision="NOT_RECOGNIZE"),
            decision_qs.delete,
            lambda: decision_qs.bulk_create([self._decision()]),
            lambda: decision_qs.bulk_update([self._decision()], ["decision"]),
            lambda: amendment_qs.update(reason="rewrite"),
            amendment_qs.delete,
            lambda: amendment_qs.bulk_create([]),
            lambda: amendment_qs.bulk_update([], ["reason"]),
        ):
            with self.assertRaisesRegex(ValueError, "APPEND_ONLY"):
                operation()

    def test_provider_default_is_versioned_and_not_placeholder(self):
        result = ProviderEvidenceResult.unavailable("SOURCE_DOWN")
        self.assertTrue(result.provider_version)
        self.assertNotIn("placeholder", result.provider_version.lower())

    def test_mysql_migration_guards_decision_amendment_and_evidence(self):
        migration = (
            Path(__file__).resolve().parents[1]
            / "migrations"
            / "0006_hrdoubleteacherfinaldecisionamendment_and_more.py"
        ).read_text(encoding="utf-8")
        for trigger in (
            "hr09_final_decision_no_update",
            "hr09_final_decision_no_delete",
            "hr09_decision_amendment_no_update",
            "hr09_decision_amendment_no_delete",
            "hr09_evidence_package_no_frozen_update",
            "hr09_evidence_item_no_frozen_insert",
            "hr09_evidence_item_no_frozen_update",
            "hr09_evidence_item_no_frozen_delete",
        ):
            self.assertIn(f"CREATE TRIGGER {trigger}", migration)
        self.assertIn("SIGNAL SQLSTATE '45000'", migration)

    def test_correction_replacement_is_allowlisted_and_normalized(self):
        source = MagicMock(
            decision="RECOGNIZE",
            recognized_level="DOUBLE_TEACHER_JUNIOR",
            effective_from=date(2026, 9, 1),
            effective_to=None,
            decision_authority="Committee",
            meeting_ref="M-1",
        )
        replacement = FinalDecisionAuthorityService._normalized_replacement(
            source,
            {
                "recognizedLevel": "DOUBLE_TEACHER_INTERMEDIATE",
                "effectiveFrom": "2026-10-01",
            },
        )
        self.assertEqual(
            replacement["recognizedLevel"], "DOUBLE_TEACHER_INTERMEDIATE"
        )
        self.assertEqual(replacement["effectiveFrom"], "2026-10-01")


class FinalDecisionAuthorityApiContractTests(SimpleTestCase):
    class User:
        is_authenticated = True
        is_superuser = False
        id = 88

        def __init__(self, permissions):
            self.permissions = set(permissions)

        def has_perm(self, code):
            return code in self.permissions

    def setUp(self):
        self.factory = RequestFactory()
        self.decision_id = uuid.uuid4()

    @patch("hr_qualification.api.access.resolve_tenant_or_raise", return_value=7)
    def test_finalize_permission_cannot_correct_or_revoke(self, _tenant):
        for endpoint in (
            views_review.final_decision_correct,
            views_review.final_decision_revoke,
        ):
            request = self.factory.post(
                "/api/v1/hr/qualifications/double-teacher/final-decisions/x",
                data=json.dumps({}),
                content_type="application/json",
            )
            request.user = self.User({"hr.qualification.review.finalize"})
            response = endpoint(request, str(self.decision_id))
            self.assertEqual(response.status_code, 403)

    def test_correction_and_revocation_are_distinct_permissions(self):
        self.assertNotEqual(
            FINAL_DECISION_CORRECT_PERMISSION,
            FINAL_DECISION_REVOKE_PERMISSION,
        )


class FrozenEvidenceInstanceContractTests(SimpleTestCase):
    def test_item_bound_to_frozen_package_cannot_save_or_delete(self):
        package = HrDoubleTeacherEvidencePackage(status="FROZEN")
        item = HrDoubleTeacherEvidenceItem(
            package_id=package,
            source_domain="HR09_CREDENTIAL",
            title="sealed",
        )
        with self.assertRaisesRegex(ValueError, "FROZEN_APPEND_ONLY"):
            item.save()
        with self.assertRaisesRegex(ValueError, "FROZEN_APPEND_ONLY"):
            item.delete()
