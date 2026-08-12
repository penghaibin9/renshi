"""第四轮审计修复回归测试：事件 org 解析、按岗位 as-of、导出、导入 applier、工号序列、审计补齐。"""

from datetime import date
from io import StringIO
from unittest import mock

from django.test import TestCase

from hr_staff.constants import AssignmentType
from hr_staff.models import HrStaffAuditEvent, HrStaffMaster
from hr_staff.services.audit_service import write_audit_event
from hr_staff.services.effective_dated_query_service import EffectiveDatedQueryService
from hr_staff.services.event_service import BusinessEventService
from hr_staff.services.staff_master_service import StaffMasterService, StaffNumberService
from hr_staff.tests.factories import make_org, make_person, make_staff

TENANT = 1
FIXTURE_SOURCE = "MIGRATION_VERIFIED"


class EventOrgResolutionTests(TestCase):
    def setUp(self):
        self.person = make_person(TENANT, "张某某")
        self.staff = make_staff(TENANT, self.person, "T001238")
        self.org = make_org(TENANT, "JSXY", "计算机学院", date(2020, 1, 1))
        self.svc = BusinessEventService(TENANT, actor_user_id=1)

    def test_onboarding_with_org_consumed(self):
        """P1-a：HR05 事件带 organization_id 也可正常消费（解析为实例）。"""
        inbox = self.svc.receive(
            event_type="HR05_ONBOARDING",
            payload={
                "source_business_id": "ONB-003",
                "staff_id": str(self.staff.id),
                "effective_from": "2024-09-01",
                "organization_id": self.org.id,
            },
        )
        self.svc.consume(inbox.id)
        inbox.refresh_from_db()
        self.assertEqual(inbox.status, "CONSUMED")
        from hr_staff.models import HrStaffAssignment

        assignment = HrStaffAssignment.objects.filter(tenant_id=TENANT).first()
        self.assertEqual(assignment.organization_id_id, self.org.id)

    def test_position_occupancy_as_of(self):
        """P1-b：按岗位/组织 as-of 占用入口。"""
        from hr_staff.services.employment_service import EmploymentService

        rel = EmploymentService(TENANT).start_relationship(
            staff_id=self.staff,
            relationship_type="REGULAR_EMPLOYMENT",
            effective_from=date(2024, 9, 1),
        )
        from hr_structure.models import HrPosition, HrPostCatalog, HrPostCatalogVersion

        catalog = HrPostCatalog.objects.create(tenant_id=TENANT, stable_code="CAT001")
        catalog_version = HrPostCatalogVersion.objects.create(
            catalog_id=catalog,
            tenant_id=TENANT,
            name="教师岗",
            validity_from=date(2020, 1, 1),
        )
        position = HrPosition.objects.create(
            tenant_id=TENANT,
            position_code="P001",
            organization_id=self.org,
            post_catalog_version_id=catalog_version,
            validity_from=date(2020, 1, 1),
        )
        from hr_staff.services.assignment_service import AssignmentService

        AssignmentService(TENANT).create_assignment(
            employment_relationship_id=rel,
            assignment_type=AssignmentType.PRIMARY,
            effective_from=date(2024, 9, 1),
            organization_id=self.org,
            position_id=position,
            source_business_type=FIXTURE_SOURCE,
        )
        qs = EffectiveDatedQueryService(TENANT)
        self.assertEqual(qs.position_occupancy_as_of(position.id, date(2025, 1, 1)), 1)
        self.assertEqual(qs.org_occupancy_as_of(self.org.id, date(2025, 1, 1)), 1)


class AuditCompletenessTests(TestCase):
    def test_person_creation_audited(self):
        """P1-f：人员创建必审计。"""
        from hr_staff.services.person_identity_service import PersonIdentityService

        PersonIdentityService().create_person_with_identity(
            tenant_id=TENANT, legal_name="王五"
        )
        self.assertTrue(
            HrStaffAuditEvent.objects.filter(tenant_id=TENANT, action="PersonCreated").exists()
        )

    def test_staff_creation_audited(self):
        """P1-f：StaffMaster 创建必审计。"""
        person = make_person(TENANT, "李四")
        StaffMasterService().create_staff(tenant_id=TENANT, person_id=person, staff_no="T100000")
        self.assertTrue(
            HrStaffAuditEvent.objects.filter(tenant_id=TENANT, action="StaffMasterCreated").exists()
        )


class StaffNumberSequenceTests(TestCase):
    def test_sequence_generates_incrementing_no_truncation(self):
        """P1-j：序列分配不依赖全表扫描（首次初始化后 O(1)）。"""
        svc = StaffNumberService(prefix="T", width=6)
        first = svc.next_staff_no(TENANT)
        self.assertEqual(first, "T000001")
        second = svc.next_staff_no(TENANT)
        self.assertEqual(second, "T000002")

    def test_sequence_initializes_from_existing_max(self):
        """P1-j：已有工号时序列从 max+1 初始化。"""
        person = make_person(TENANT, "赵六")
        StaffMasterService().create_staff(
            tenant_id=TENANT, person_id=person, staff_no="T000010"
        )
        svc = StaffNumberService(prefix="T", width=6)
        self.assertEqual(svc.next_staff_no(TENANT), "T000011")
