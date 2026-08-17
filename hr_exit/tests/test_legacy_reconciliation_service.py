import inspect
import uuid
from datetime import date

from django.test import SimpleTestCase

from hr_exit.models import ExitFact
from hr_exit.services.legacy_reconciliation_service import LegacyExitReconciliationService


class StubLegacyExitReconciliationService(LegacyExitReconciliationService):
    def __init__(self, *, legacy_rows, staff_map, facts_by_person, total=None):
        super().__init__(tenant_id=7)
        self.legacy_rows = legacy_rows
        self.staff_map = staff_map
        self.facts_by_person = facts_by_person
        self.total = len(legacy_rows) if total is None else total

    def _legacy_rows(self, limit):
        return self.total, self.legacy_rows[:limit]

    def _staff_map(self, legacy_employee_ids):
        return self.staff_map

    def _facts_by_person(self, person_ids):
        return self.facts_by_person


class Hr16LegacyReconciliationServiceTests(SimpleTestCase):
    def _legacy(
        self,
        *,
        stage_type="archived",
        process_status="completed",
        notice_end=date(2026, 8, 31),
    ):
        return {
            "id": 91,
            "employee_id_id": 18,
            "notice_period_starts": date(2026, 8, 1),
            "notice_period_ends": notice_end,
            "stage_id_id": 4,
            "stage_id__type": stage_type,
            "stage_id__title": "Archived",
            "stage_id__offboarding_id__status": process_status,
        }

    def _authority(self, *, person_id, status=ExitFact.Status.EFFECTIVE):
        return {
            "id": uuid.uuid4(),
            "person_id": person_id,
            "employment_relationship_id": uuid.uuid4(),
            "exit_type": "RESIGNATION",
            "employment_end_date": date(2026, 8, 31),
            "last_working_date": date(2026, 8, 30),
            "status": status,
            "supersedes_fact_id": None,
        }

    def test_linked_terminal_candidate_requires_mapping_review_even_when_dates_equal(self):
        staff_id = uuid.uuid4()
        person_id = uuid.uuid4()
        svc = StubLegacyExitReconciliationService(
            legacy_rows=[self._legacy()],
            staff_map={18: {"staff_id": staff_id, "person_id": person_id}},
            facts_by_person={person_id: [self._authority(person_id=person_id)]},
        )

        snapshot = svc.snapshot()

        self.assertEqual(snapshot["status"], "PARTIAL")
        self.assertFalse(snapshot["legacyAuthority"])
        self.assertEqual(
            snapshot["mappingPolicy"],
            "NOTICE_PERIOD_END_IS_NOT_EMPLOYMENT_END",
        )
        item = snapshot["items"][0]
        self.assertEqual(item["reconciliation"], "LINKED_REVIEW_REQUIRED")
        self.assertTrue(item["legacyTerminalCandidate"])
        self.assertFalse(item["legacyAuthority"])
        self.assertEqual(item["legacyDateSemantics"], "NOTICE_PERIOD_END")
        self.assertEqual(item["authorityDateSemantics"], "EMPLOYMENT_END")

    def test_non_terminal_legacy_row_is_inventory_only(self):
        svc = StubLegacyExitReconciliationService(
            legacy_rows=[
                self._legacy(stage_type="handover", process_status="ongoing")
            ],
            staff_map={},
            facts_by_person={},
        )

        snapshot = svc.snapshot()

        self.assertEqual(snapshot["status"], "COMPLETE")
        self.assertEqual(snapshot["counts"]["legacyNonFinal"], 1)
        self.assertEqual(snapshot["items"][0]["reconciliation"], "LEGACY_NON_FINAL")

    def test_unmapped_terminal_legacy_staff_is_partial(self):
        svc = StubLegacyExitReconciliationService(
            legacy_rows=[self._legacy()],
            staff_map={},
            facts_by_person={},
        )

        snapshot = svc.snapshot()

        self.assertEqual(snapshot["status"], "PARTIAL")
        self.assertEqual(snapshot["counts"]["unmappedStaff"], 1)
        self.assertEqual(snapshot["items"][0]["reconciliation"], "UNMAPPED_STAFF")

    def test_pending_authority_fact_is_not_misclassified_as_complex(self):
        staff_id = uuid.uuid4()
        person_id = uuid.uuid4()
        pending = self._authority(
            person_id=person_id,
            status=ExitFact.Status.EFFECT_PENDING,
        )
        svc = StubLegacyExitReconciliationService(
            legacy_rows=[self._legacy()],
            staff_map={18: {"staff_id": staff_id, "person_id": person_id}},
            facts_by_person={person_id: [pending]},
        )

        snapshot = svc.snapshot()

        self.assertEqual(snapshot["status"], "PARTIAL")
        self.assertEqual(snapshot["counts"]["authorityNotEffective"], 1)
        self.assertEqual(
            snapshot["items"][0]["reconciliation"],
            "AUTHORITY_NOT_EFFECTIVE",
        )

    def test_revision_or_revocation_chain_is_not_flattened_to_false_match(self):
        staff_id = uuid.uuid4()
        person_id = uuid.uuid4()
        effective = self._authority(person_id=person_id)
        revised = self._authority(person_id=person_id, status=ExitFact.Status.REVISED)
        revised["supersedes_fact_id"] = effective["id"]
        svc = StubLegacyExitReconciliationService(
            legacy_rows=[self._legacy()],
            staff_map={18: {"staff_id": staff_id, "person_id": person_id}},
            facts_by_person={person_id: [effective, revised]},
        )

        snapshot = svc.snapshot()

        self.assertEqual(snapshot["status"], "PARTIAL")
        self.assertEqual(snapshot["items"][0]["reconciliation"], "AUTHORITY_COMPLEX")

    def test_terminal_candidate_without_notice_end_is_partial(self):
        staff_id = uuid.uuid4()
        person_id = uuid.uuid4()
        svc = StubLegacyExitReconciliationService(
            legacy_rows=[self._legacy(notice_end=None)],
            staff_map={18: {"staff_id": staff_id, "person_id": person_id}},
            facts_by_person={person_id: [self._authority(person_id=person_id)]},
        )

        snapshot = svc.snapshot()

        self.assertEqual(snapshot["status"], "PARTIAL")
        self.assertEqual(snapshot["counts"]["legacyNoticeEndMissing"], 1)
        self.assertEqual(
            snapshot["items"][0]["reconciliation"],
            "LEGACY_NOTICE_END_MISSING",
        )

    def test_legacy_reader_uses_entire_then_explicit_tenant_predicate(self):
        legacy_source = inspect.getsource(LegacyExitReconciliationService._legacy_rows)
        staff_source = inspect.getsource(LegacyExitReconciliationService._staff_map)
        fact_source = inspect.getsource(
            LegacyExitReconciliationService._facts_by_person
        )
        self.assertIn("OffboardingEmployee.objects.entire()", legacy_source)
        self.assertIn(
            "employee_id__employee_work_info__company_id=self.tenant_id",
            legacy_source,
        )
        self.assertIn("tenant_id=self.tenant_id", staff_source)
        self.assertIn("tenant_id=self.tenant_id", fact_source)
