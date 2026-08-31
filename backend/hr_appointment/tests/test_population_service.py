import uuid
from datetime import date

from django.test import TestCase

from hr_appointment.models import AppointmentBatch
from hr_appointment.population_models import AppointmentPopulationMemberSnapshot
from hr_appointment.services.population_service import (
    AppointmentPopulationError,
    AppointmentPopulationService,
)
from hr_staff.models import HrEmploymentRelationship, HrPerson, HrStaffAssignment, HrStaffMaster


class AppointmentPopulationServiceTests(TestCase):
    def setUp(self):
        self.tenant = 77
        self.batch = AppointmentBatch.objects.create(
            tenant_id=self.tenant,
            batch_no="POP-2026",
            name="2026 人口冻结批次",
            policy_version_id=uuid.uuid4(),
            status=AppointmentBatch.Status.DRAFT,
        )
        self.service = AppointmentPopulationService(self.tenant, actor_user_id=9)
        self.as_of = date(2026, 8, 1)

    def _active_staff(self, *, tenant=77, no="T001", with_primary=True):
        person = HrPerson.objects.create(tenant_id=tenant, legal_name=f"教师-{no}")
        staff = HrStaffMaster.objects.create(
            tenant_id=tenant,
            person_id=person,
            staff_no=no,
            staff_category_code="TEACHER",
        )
        relationship = HrEmploymentRelationship.objects.create(
            tenant_id=tenant,
            staff_id=staff,
            relationship_type="REGULAR_EMPLOYMENT",
            employment_type="FULL_TIME",
            effective_from=date(2025, 1, 1),
            status="ACTIVE",
            version=3,
        )
        assignment = None
        if with_primary:
            assignment = HrStaffAssignment.objects.create(
                tenant_id=tenant,
                employment_relationship_id=relationship,
                assignment_type="PRIMARY",
                assignment_role_code="TEACHER",
                effective_from=date(2025, 1, 1),
                status="ACTIVE",
                version=4,
            )
        return person, staff, relationship, assignment

    def test_freeze_reads_only_tenant_active_effective_dated_hr03_facts(self):
        person, staff, relationship, assignment = self._active_staff()
        self._active_staff(tenant=88, no="FOREIGN")

        ended_person, ended_staff, ended_relationship, _ = self._active_staff(
            no="ENDED", with_primary=False
        )
        ended_relationship.effective_to = date(2026, 7, 1)
        ended_relationship.save(update_fields=["effective_to", "updated_at"])

        snapshot = self.service.freeze_from_hr03(self.batch.id, as_of_date=self.as_of)

        self.assertEqual(snapshot.member_count, 1)
        self.assertEqual(snapshot.as_of_date, self.as_of)
        self.assertEqual(snapshot.source_domain, "HR03")
        self.assertEqual(len(snapshot.content_hash), 64)
        member = AppointmentPopulationMemberSnapshot.objects.get(snapshot=snapshot)
        self.assertEqual(member.person_id, person.id)
        self.assertEqual(member.staff_id, staff.id)
        self.assertEqual(member.employment_relationship_refs_json[0]["id"], str(relationship.id))
        self.assertEqual(member.employment_relationship_refs_json[0]["version"], 3)
        self.assertEqual(member.primary_assignment_refs_json[0]["id"], str(assignment.id))
        self.assertEqual(member.primary_assignment_refs_json[0]["version"], 4)
        self.assertFalse(
            AppointmentPopulationMemberSnapshot.objects.filter(person_id=ended_person.id).exists()
        )

    def test_freeze_is_exact_idempotent_and_asof_change_conflicts(self):
        self._active_staff()
        first = self.service.freeze_from_hr03(self.batch.id, as_of_date=self.as_of)
        second = self.service.freeze_from_hr03(self.batch.id, as_of_date=self.as_of)
        self.assertEqual(first.id, second.id)

        with self.assertRaises(AppointmentPopulationError) as ctx:
            self.service.freeze_from_hr03(self.batch.id, as_of_date=date(2026, 8, 2))
        self.assertEqual(ctx.exception.code, "APPOINTMENT_POPULATION_IDEMPOTENCY_CONFLICT")

    def test_empty_population_fails_closed_without_creating_snapshot(self):
        with self.assertRaises(AppointmentPopulationError) as ctx:
            self.service.freeze_from_hr03(self.batch.id, as_of_date=self.as_of)
        self.assertEqual(ctx.exception.code, "APPOINTMENT_POPULATION_EMPTY")
        self.assertFalse(hasattr(self.batch, "population_snapshot"))

    def test_snapshot_member_is_immutable(self):
        self._active_staff()
        snapshot = self.service.freeze_from_hr03(self.batch.id, as_of_date=self.as_of)
        member = AppointmentPopulationMemberSnapshot.objects.get(snapshot=snapshot)
        member.staff_category_code = "OTHER"

        with self.assertRaisesRegex(ValueError, "APPOINTMENT_POPULATION_MEMBER_IMMUTABLE"):
            member.save(update_fields=["staff_category_code", "updated_at"])
