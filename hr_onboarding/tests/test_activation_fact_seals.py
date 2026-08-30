from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from hr_onboarding.api.exceptions import TenantContextRequiredError, VersionConflictError
from hr_onboarding.models.activation import (
    HrOnboardingActivationAmendment,
    HrOnboardingActivationSnapshot,
)
from hr_onboarding.services.activation_fact_service import ActivationFactService


class ActivationFactOrmSealTests(SimpleTestCase):
    def _snapshot(self):
        snapshot = HrOnboardingActivationSnapshot(
            id=uuid4(),
            tenant_id=7,
            case_id=uuid4(),
            person_id=uuid4(),
            staff_master_id=uuid4(),
            employment_id=uuid4(),
            assignment_id=uuid4(),
            staff_no="T-0007",
            source_type="HR04_HIRE",
            source_id="hire-7",
            hr04_proposed_hire_id="proposed-7",
            hr04_application_id="application-7",
        )
        snapshot._state.fields_cache["case"] = SimpleNamespace(
            tenant_id=7,
            source_type="HR04_HIRE",
            source_id="hire-7",
            hr04_proposed_hire_id="proposed-7",
            hr04_application_id="application-7",
        )
        snapshot._prepare_seal()
        return snapshot

    def test_initial_snapshot_hash_is_stable_and_sealed(self):
        snapshot = self._snapshot()
        self.assertEqual(len(snapshot.content_hash), 64)
        self.assertEqual(snapshot.content_hash, snapshot.calculate_content_hash())
        self.assertIsNotNone(snapshot.sealed_at)

    def test_initial_snapshot_instance_update_and_delete_are_blocked(self):
        snapshot = self._snapshot()
        snapshot._state.adding = False
        with self.assertRaisesMessage(ValidationError, "HR05_ACTIVATION_FACT_IMMUTABLE"):
            snapshot.save()
        with self.assertRaisesMessage(ValidationError, "HR05_ACTIVATION_FACT_IMMUTABLE"):
            snapshot.delete()

    def test_snapshot_queryset_update_and_delete_are_blocked_before_sql(self):
        queryset = HrOnboardingActivationSnapshot.objects.all()
        with self.assertRaisesMessage(ValidationError, "HR05_ACTIVATION_FACT_IMMUTABLE"):
            queryset.update(staff_no="tampered")
        with self.assertRaisesMessage(ValidationError, "HR05_ACTIVATION_FACT_IMMUTABLE"):
            queryset.delete()

    def test_amendment_instance_and_queryset_are_append_only(self):
        amendment = HrOnboardingActivationAmendment(
            id=uuid4(),
            tenant_id=7,
            snapshot_id=uuid4(),
            sequence_no=1,
            action=HrOnboardingActivationAmendment.Action.CORRECTION,
            idempotency_key="idem-7",
            request_hash="a" * 64,
            reason="fix staff number",
            before_snapshot_json={"staffNo": "old"},
            after_snapshot_json={"staffNo": "new"},
        )
        amendment._prepare_seal()
        self.assertEqual(len(amendment.content_hash), 64)
        amendment._state.adding = False
        with self.assertRaisesMessage(
            ValidationError, "HR05_ACTIVATION_AMENDMENT_IMMUTABLE"
        ):
            amendment.save()
        with self.assertRaisesMessage(
            ValidationError, "HR05_ACTIVATION_FACT_IMMUTABLE"
        ):
            HrOnboardingActivationAmendment.objects.all().update(reason="tamper")


class ActivationFactParentChainTests(SimpleTestCase):
    def _linked(self):
        person_id, staff_id, employment_id, assignment_id = (
            uuid4(),
            uuid4(),
            uuid4(),
            uuid4(),
        )
        case = SimpleNamespace(
            tenant_id=7,
            source_type="HR04_HIRE",
            source_id="hire-7",
            hr04_proposed_hire_id="proposed-7",
            hr04_application_id="application-7",
            hr03_person_id=person_id,
            hr03_staff_master_id=staff_id,
            hr03_employment_id=employment_id,
            hr03_assignment_id=assignment_id,
        )
        snapshot = SimpleNamespace(
            tenant_id=7,
            source_type=case.source_type,
            source_id=case.source_id,
            hr04_proposed_hire_id=case.hr04_proposed_hire_id,
            hr04_application_id=case.hr04_application_id,
            person_id=person_id,
            staff_master_id=staff_id,
            employment_id=employment_id,
            assignment_id=assignment_id,
            case=case,
        )
        return snapshot

    def test_valid_tenant_person_and_hire_chain_passes(self):
        ActivationFactService._assert_parent_chain(self._linked())

    def test_cross_tenant_chain_fails_closed(self):
        snapshot = self._linked()
        snapshot.tenant_id = 8
        with self.assertRaises(TenantContextRequiredError):
            ActivationFactService._assert_parent_chain(snapshot)

    def test_changed_person_or_hire_parent_is_rejected(self):
        snapshot = self._linked()
        snapshot.hr04_proposed_hire_id = "other-hire"
        with self.assertRaises(VersionConflictError):
            ActivationFactService._assert_parent_chain(snapshot)

        snapshot = self._linked()
        snapshot.person_id = uuid4()
        with self.assertRaises(VersionConflictError):
            ActivationFactService._assert_parent_chain(snapshot)

    def test_revocation_projects_terminal_effective_status(self):
        snapshot = SimpleNamespace(
            id=uuid4(),
            case_id=uuid4(),
            tenant_id=7,
            content_hash="a" * 64,
        )
        latest = SimpleNamespace(
            id=uuid4(),
            action=HrOnboardingActivationAmendment.Action.REVOCATION,
            sequence_no=2,
            after_snapshot_json={"revoked": True},
            content_hash="b" * 64,
        )
        result = ActivationFactService(tenant_id=7)._serialize(snapshot, latest)
        self.assertEqual(result["status"], "REVOKED")
        self.assertEqual(result["version"], 3)
        self.assertTrue(result["payload"]["revoked"])


class ActivationFactMySqlSealContractTests(SimpleTestCase):
    def test_migration_contains_all_six_mysql_trigger_seals(self):
        migration = (
            Path(__file__).resolve().parents[1]
            / "migrations"
            / "0013_alter_hronboardingpermissionmeta_options_and_more.py"
        ).read_text(encoding="utf-8")
        for trigger in (
            "hr05_activation_snapshot_bi_seal",
            "hr05_activation_snapshot_bu_seal",
            "hr05_activation_snapshot_bd_seal",
            "hr05_activation_amendment_bi_seal",
            "hr05_activation_amendment_bu_seal",
            "hr05_activation_amendment_bd_seal",
        ):
            self.assertIn(trigger, migration)
        self.assertIn("HR05_ACTIVATION_PARENT_CHAIN_INVALID", migration)
        self.assertIn("HR05_ACTIVATION_AMENDMENT_PREDECESSOR_INVALID", migration)
        self.assertIn("HR05_ACTIVATION_FACT_ALREADY_REVOKED", migration)
