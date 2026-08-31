from datetime import date
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from horilla.hr_event_registry import global_event_registry
from horilla.hr_permission_registry import permission_registry
from hr_contracts.events import EVENT_AGREEMENT_CORRECTED, EVENT_AGREEMENT_VOIDED
from hr_contracts.models import (
    HrContractAgreement,
    HrContractVersion,
    HrContractVersionAction,
)
from hr_contracts.permissions import PERM_VERSION_CORRECT, PERM_VERSION_VOID
from hr_contracts.services.version_action_service import ContractVersionActionService


class ContractAuthoritySealContractTests(SimpleTestCase):
    def test_mysql_migration_seals_instance_bulk_and_raw_sql_paths(self):
        migration = (
            Path(__file__).resolve().parents[1]
            / "migrations"
            / "0003_hrcontractversionaction_and_more.py"
        ).read_text(encoding="utf-8")
        for trigger in (
            "hr07_agreement_guard_update",
            "hr07_agreement_guard_delete",
            "hr07_version_guard_update",
            "hr07_version_guard_delete",
            "hr07_version_action_no_update",
            "hr07_version_action_no_delete",
        ):
            self.assertIn(f"CREATE TRIGGER {trigger}", migration)
        self.assertIn("OLD.content_snapshot_json <=> NEW.content_snapshot_json", migration)
        self.assertIn("HR07_SIGNED_VERSION_NO_DELETE", migration)
        self.assertIn("HR07_VERSION_STATUS_TRANSITION_INVALID", migration)

    def test_correction_void_permissions_and_events_are_registered(self):
        self.assertEqual(permission_registry.get(PERM_VERSION_CORRECT).module_code, "HR07")
        self.assertEqual(permission_registry.get(PERM_VERSION_VOID).module_code, "HR07")
        self.assertEqual(global_event_registry.get(EVENT_AGREEMENT_CORRECTED).module_code, "HR07")
        self.assertEqual(global_event_registry.get(EVENT_AGREEMENT_VOIDED).module_code, "HR07")


class ContractVersionActionDatabaseTests(TestCase):
    def setUp(self):
        self.tenant_id = 701
        self.agreement = HrContractAgreement.objects.create(
            tenant_id=self.tenant_id,
            agreement_no="HR07-SEAL-001",
            staff_id=uuid4(),
            employment_relationship_id=uuid4(),
            agreement_title="sealed contract",
            agreement_type="EMPLOYMENT",
            status=HrContractAgreement.Status.ACTIVE,
            current_version_no=1,
        )
        self.version = HrContractVersion.objects.create(
            tenant_id=self.tenant_id,
            agreement=self.agreement,
            version_no=1,
            version_type=HrContractVersion.VersionType.INITIAL,
            effective_from=date(2026, 1, 1),
            signed_at=timezone.now(),
            signed_document_ref="private://signed/v1",
            content_snapshot_json={"salaryClause": "original"},
            content_hash="a" * 64,
            status=HrContractVersion.Status.EFFECTIVE,
        )

    @patch("hr_contracts.services.version_action_service.emit_registered_event")
    def test_correction_appends_successor_and_retry_is_event_idempotent(self, emit):
        service = ContractVersionActionService(self.tenant_id, actor_user_id=91)
        kwargs = {
            "agreement_id": self.agreement.id,
            "source_version_id": self.version.id,
            "content_snapshot": {"salaryClause": "corrected"},
            "signed_at": timezone.now(),
            "signed_document_ref": "private://signed/v2",
            "reason": "clerical error",
            "evidence_ref": "evidence://ticket/7",
            "authority_ref": "approval://board/7",
            "idempotency_key": "correct-001",
        }
        first = service.correct(**kwargs)
        retried = service.correct(**kwargs)
        self.assertEqual(first.id, retried.id)
        self.assertEqual(emit.call_count, 1)

        self.version.refresh_from_db()
        self.agreement.refresh_from_db()
        successor = first.successor_version
        self.assertEqual(self.version.status, HrContractVersion.Status.VOID)
        self.assertEqual(successor.version_type, HrContractVersion.VersionType.CORRECTION)
        self.assertEqual(successor.supersedes_version_id, self.version.id)
        self.assertEqual(self.agreement.current_version_no, 2)

        with self.assertRaises(ValidationError):
            HrContractVersion.objects.filter(pk=successor.pk).update(content_hash="b" * 64)
        with self.assertRaises(ValidationError):
            successor.delete()
        with self.assertRaises(ValidationError):
            HrContractVersionAction.objects.filter(pk=first.pk).delete()

    @patch("hr_contracts.services.version_action_service.emit_registered_event")
    def test_void_is_append_only_and_conflicting_retry_is_rejected(self, emit):
        service = ContractVersionActionService(self.tenant_id, actor_user_id=92)
        action = service.void(
            agreement_id=self.agreement.id,
            source_version_id=self.version.id,
            reason="duplicate contract",
            evidence_ref="evidence://duplicate/1",
            authority_ref="approval://legal/1",
            idempotency_key="void-001",
        )
        self.assertEqual(action.kind, HrContractVersionAction.Kind.VOID)
        self.version.refresh_from_db()
        self.agreement.refresh_from_db()
        self.assertEqual(self.version.status, HrContractVersion.Status.VOID)
        self.assertEqual(self.agreement.status, HrContractAgreement.Status.ARCHIVED)
        self.assertEqual(self.agreement.current_version_no, 0)
        self.assertEqual(emit.call_count, 1)

        with self.assertRaises(ValidationError):
            action.delete()
