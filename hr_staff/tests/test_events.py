"""S10 · BusinessEventService 测试：幂等接收、HR16 离退不 DELETE、HR13 投影、outbox。"""

from datetime import date

from django.test import TestCase

from hr_staff.constants import AssignmentType
from hr_staff.models import (
    HrBusinessEventInbox,
    HrEmploymentRelationship,
    HrOutboxEvent,
    HrStaffAssignment,
)
from hr_staff.services.assignment_service import AssignmentService
from hr_staff.services.employment_service import EmploymentService
from hr_staff.services.event_service import BusinessEventService
from hr_staff.tests.factories import make_org, make_person, make_staff

TENANT = 1
FIXTURE_SOURCE = "MIGRATION_VERIFIED"


class BusinessEventTests(TestCase):
    def setUp(self):
        self.person = make_person(TENANT, "张某某")
        self.staff = make_staff(TENANT, self.person, "T001238")
        self.org = make_org(TENANT, "JSXY", "计算机学院", date(2020, 1, 1))
        self.svc = BusinessEventService(TENANT, actor_user_id=1)

    def test_receive_is_idempotent(self):
        payload = {
            "source_business_type": "HR05_ONBOARDING",
            "source_business_id": "ONB-001",
            "staff_id": self.staff.id,
            "effective_from": "2024-09-01",
        }
        first = self.svc.receive(event_type="HR05_ONBOARDING", payload=payload)
        second = self.svc.receive(event_type="HR05_ONBOARDING", payload=payload)
        self.assertEqual(first.id, second.id)
        self.assertEqual(
            HrBusinessEventInbox.objects.filter(
                idempotency_key="HR05_ONBOARDING:ONB-001"
            ).count(),
            1,
        )

    def test_consume_onboarding_creates_relationship_and_assignment(self):
        inbox = self.svc.receive(
            event_type="HR05_ONBOARDING",
            payload={
                "source_business_id": "ONB-002",
                "staff_id": self.staff.id,
                "effective_from": "2024-09-01",
                "legacy_department_id": 7,
            },
        )
        self.svc.consume(inbox.id)
        inbox.refresh_from_db()
        self.assertEqual(inbox.status, "CONSUMED")
        self.assertEqual(
            HrEmploymentRelationship.objects.filter(tenant_id=TENANT, staff_id=self.staff).count(), 1
        )
        assignment = HrStaffAssignment.objects.filter(tenant_id=TENANT).first()
        self.assertEqual(assignment.legacy_department_id, 7)
        self.assertEqual(assignment.assignment_type, AssignmentType.PRIMARY)

    def test_consume_exit_keeps_history(self):
        """HR16 离职：关系/任职段 ENDED，Person/Staff 不 DELETE，历史保留。"""
        rel = EmploymentService(TENANT).start_relationship(
            staff_id=self.staff,
            relationship_type="REGULAR_EMPLOYMENT",
            effective_from=date(2020, 9, 1),
        )
        AssignmentService(TENANT).create_assignment(
            employment_relationship_id=rel,
            assignment_type=AssignmentType.PRIMARY,
            effective_from=date(2020, 9, 1),
            organization_id=self.org,
            source_business_type=FIXTURE_SOURCE,
        )
        inbox = self.svc.receive(
            event_type="HR16_EXIT",
            payload={
                "source_business_id": "EXIT-001",
                "staff_id": self.staff.id,
                "employment_relationship_id": str(rel.id),
                "effective_to": "2026-08-01",
                "reason_code": "RESIGNATION",
            },
        )
        self.svc.consume(inbox.id)
        rel.refresh_from_db()
        self.assertEqual(rel.status, "ENDED")
        self.assertTrue(HrStaffAssignment.objects.filter(tenant_id=TENANT).exists())
        self.staff.refresh_from_db()
        self.assertIsNotNone(self.staff.id)

    def test_consume_retire_writes_status_history(self):
        rel = EmploymentService(TENANT).start_relationship(
            staff_id=self.staff,
            relationship_type="REGULAR_EMPLOYMENT",
            effective_from=date(2020, 9, 1),
        )
        inbox = self.svc.receive(
            event_type="HR16_EXIT",
            payload={
                "source_business_id": "RET-001",
                "staff_id": self.staff.id,
                "employment_relationship_id": str(rel.id),
                "effective_to": "2026-08-01",
                "reason_code": "RETIREMENT",
            },
        )
        self.svc.consume(inbox.id)
        from hr_staff.models import HrStatusHistory

        status = HrStatusHistory.objects.filter(tenant_id=TENANT, staff_id=self.staff).first()
        self.assertEqual(status.status_code, "RETIRED")

    def test_consume_title_appointment_writes_credential_projection(self):
        inbox = self.svc.receive(
            event_type="HR13_TITLE_APPOINTMENT",
            payload={
                "source_business_id": "TITLE-001",
                "staff_id": self.staff.id,
                "title_name": "副教授",
                "title_level": "副教授",
                "effective_date": "2026-06-01",
            },
        )
        self.svc.consume(inbox.id)
        from hr_staff.models import HrCredential

        cred = HrCredential.objects.filter(tenant_id=TENANT, staff_id=self.staff).first()
        self.assertEqual(cred.credential_name, "副教授")
        self.assertEqual(cred.source_domain, "HR13")

    def test_outbox_emit(self):
        event = self.svc.emit(
            event_type="PrimaryAssignmentChanged",
            payload={"staffId": str(self.staff.id), "effectiveDate": "2026-08-01"},
            correlation_id="req-1",
        )
        self.assertEqual(event.event_type, "PrimaryAssignmentChanged")
        self.assertEqual(event.status, "PENDING")
        self.assertNotIn("identity", event.payload_json)

    def test_consume_canonical_event_names(self):
        """99 总册 PATCH-05：canonical 事件名（StaffActivated/ProfessionalTitleResultEffective 等）可被消费。"""
        inbox = self.svc.receive(
            event_type="StaffActivated",
            payload={
                "source_business_type": "HR05_ONBOARDING",
                "source_business_id": "ONB-CANON-001",
                "staff_id": self.staff.id,
                "effective_from": "2024-09-01",
                "legacy_department_id": 8,
            },
        )
        self.svc.consume(inbox.id)
        inbox.refresh_from_db()
        self.assertEqual(inbox.status, "CONSUMED")
        self.assertEqual(
            HrEmploymentRelationship.objects.filter(tenant_id=TENANT, staff_id=self.staff).count(), 1
        )

        inbox2 = self.svc.receive(
            event_type="ProfessionalTitleResultEffective",
            payload={
                "source_business_id": "TITLE-CANON-001",
                "staff_id": self.staff.id,
                "title_name": "教授",
                "title_level": "教授",
                "effective_date": "2026-06-01",
            },
        )
        self.svc.consume(inbox2.id)
        from hr_staff.models import HrCredential

        cred = HrCredential.objects.filter(tenant_id=TENANT, staff_id=self.staff).first()
        self.assertEqual(cred.credential_name, "教授")

        unknown = self.svc.receive(
            event_type="NotARealEvent",
            payload={"source_business_id": "X", "staff_id": self.staff.id},
        )
        from hr_staff.services.event_service import EventConsumptionError

        with self.assertRaises(EventConsumptionError):
            self.svc.consume(unknown.id)
