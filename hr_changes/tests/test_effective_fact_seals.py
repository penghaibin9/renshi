from pathlib import Path

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from hr_changes.constants import CaseStatus
from hr_changes.models import (
    HrChangeAuthorityReceipt,
    HrChangeEffectiveSnapshot,
    HrChangeRescind,
)
from hr_changes.services.authority_receipt_service import effective_execution_chain
from hr_changes.services.correction_service import CorrectionService
from hr_changes.services.rescind_service import RescindService
from hr_changes.tests.factories import make_case


TENANT = 6060


class EffectiveFactSealContractTests(SimpleTestCase):
    def test_orm_bulk_and_delete_guards_fail_before_database_access(self):
        snapshot = HrChangeEffectiveSnapshot()
        receipt = HrChangeAuthorityReceipt()
        with self.assertRaisesRegex(ValueError, "IMMUTABLE"):
            snapshot.delete()
        with self.assertRaisesRegex(ValueError, "IMMUTABLE"):
            receipt.delete()
        with self.assertRaisesRegex(ValueError, "IMMUTABLE"):
            HrChangeEffectiveSnapshot.objects.none().update(checksum="tamper")
        with self.assertRaisesRegex(ValueError, "IMMUTABLE"):
            HrChangeAuthorityReceipt.objects.none().delete()
        with self.assertRaisesRegex(ValueError, "BULK_CREATE_FORBIDDEN"):
            HrChangeEffectiveSnapshot.objects.bulk_create([snapshot])

    def test_mysql_contract_seals_raw_sql_and_parent_lineage(self):
        migration = Path(__file__).resolve().parents[1].joinpath(
            "migrations", "0007_hrchangeauthorityreceipt_and_more.py"
        ).read_text(encoding="utf-8")
        for marker in (
            "hr_changes_hrchangeeffectivesnapshot_seal_insert",
            "hr06_change_authority_receipt_seal_insert",
            "HR06_EXECUTION_PARENT_LINEAGE_INVALID",
            "HR06_HR03_PROVIDER_RECEIPT_INVALID",
            "HR06_RESCIND_CANNOT_CLAIM_HR03_EFFECT",
            "BEFORE UPDATE ON",
            "BEFORE DELETE ON",
        ):
            self.assertIn(marker, migration)


class EffectiveFactSealDatabaseTests(TestCase):
    def _snapshot(self, case):
        return HrChangeEffectiveSnapshot.objects.create(
            change_case_id=case,
            applied_at=timezone.now(),
            effective_at=case.requested_effective_at,
            before_json={"assignment": "source"},
            after_json={"assignment": "target"},
            source_fact_ids_json=["source-assignment"],
            target_fact_ids_json=["target-assignment"],
            checksum="a" * 64,
        )

    def test_execution_snapshot_is_hr03_boundary_and_immutable(self):
        case = make_case(TENANT, status=CaseStatus.EFFECTIVE)
        snapshot = self._snapshot(case)
        self.assertEqual(snapshot.tenant_id, TENANT)
        self.assertEqual(snapshot.authority_domain, "HR03")
        self.assertEqual(len(snapshot.content_hash), 64)
        snapshot.after_json = {"assignment": "tamper"}
        with self.assertRaisesRegex(ValueError, "IMMUTABLE"):
            snapshot.save()
        with self.assertRaisesRegex(ValueError, "IMMUTABLE"):
            HrChangeEffectiveSnapshot.objects.filter(id=snapshot.id).delete()

    def test_hr03_correction_appends_sealed_provider_receipt(self):
        case = make_case(TENANT, status=CaseStatus.EFFECTIVE)
        self._snapshot(case)
        service = CorrectionService(TENANT, actor_user_id=9001)
        correction = service.create_correction(
            case_id=case.id,
            correction_type="TARGET_VALUE",
            requested_values={"fields": {"person.preferred_name": "正式更正名"}},
            reason="录入错误",
            authority_version=case.staff_master_id.version,
            idempotency_key="seal-create-1",
            case_version=case.version,
        )
        correction = service.submit(correction.id)
        correction = service.approve(correction.id)
        result = service.apply(
            correction.id,
            expected_version=correction.version,
            idempotency_key="seal-apply-1",
        )
        receipt = case.authority_receipts.get()
        self.assertEqual(result.status, "APPLIED")
        self.assertEqual(receipt.kind, "CORRECTION")
        self.assertTrue(receipt.authority_effect)
        self.assertEqual(receipt.provider_code, "HR03_FORMAL_CORRECTION")
        self.assertEqual(str(receipt.provider_case_id), str(result.provider_case_id))
        self.assertEqual(len(receipt.content_hash), 64)
        replay = service.apply(
            correction.id,
            expected_version=correction.version,
            idempotency_key="seal-apply-1",
        )
        self.assertEqual(replay.id, result.id)
        self.assertEqual(case.authority_receipts.count(), 1)

    def test_rescind_receipt_explicitly_cannot_claim_hr03_reversal(self):
        case = make_case(TENANT, status=CaseStatus.EFFECTIVE)
        self._snapshot(case)
        service = RescindService(TENANT, actor_user_id=1)
        rescind = service.request_rescind(case_id=case.id, reason="政策调整")
        service.approve_rescind(rescind.id)
        executed = service.execute_rescind(rescind.id)
        receipt = case.authority_receipts.get()
        self.assertEqual(executed.status, HrChangeRescind.Status.RESCINDED)
        self.assertEqual(receipt.kind, "ORCHESTRATION_RESCIND")
        self.assertFalse(receipt.authority_effect)
        self.assertEqual(receipt.provider_code, "HR06_ORCHESTRATION_ONLY")
        self.assertFalse(receipt.payload_json["hr03FactsReversed"])
        chain = effective_execution_chain(case)
        self.assertEqual(chain["authorityOwner"], "HR03")
        self.assertFalse(chain["receipts"][0]["authorityEffect"])

    def test_cross_tenant_snapshot_parent_is_rejected(self):
        case = make_case(TENANT, status=CaseStatus.EFFECTIVE)
        case.staff_master_id.tenant_id = TENANT + 1
        case.staff_master_id.save(update_fields=["tenant_id"])
        with self.assertRaisesRegex(ValueError, "TENANT_MISMATCH"):
            self._snapshot(case)
