from datetime import date
from unittest.mock import patch

from django.test import TestCase

from hr_staff.models import HrOutboxEvent
from hr_structure.authority_registry import (
    EVENT_ORGANIZATION_CHANGED,
    EVENT_ORGANIZATION_CREATED,
    EVENT_POSITION_CREATED,
    EVENT_REORGANIZATION_EFFECTIVE,
    EVENT_RESERVATION_COMMITTED,
    EVENT_RESERVATION_HELD,
    EVENT_STAFFING_PLAN_APPROVED,
)
from hr_structure.models import HrOrganization, HrStructureChangeItem
from hr_structure.scope import Hr02Scope
from hr_structure.services.organization_change import OrganizationChangeService
from hr_structure.services.position import PositionService
from hr_structure.services.post_catalog import PostCatalogService
from hr_structure.services.reorganization import ReorganizationService
from hr_structure.services.staffing_plan import StaffingPlanService


class Hr02RegisteredOutboxTests(TestCase):
    tenant_id = 701

    def setUp(self):
        self.today = date.today()
        self.scope = Hr02Scope("SCHOOL", tenant_id=self.tenant_id)
        self.organization_service = OrganizationChangeService(self.scope, actor="w1-test")

    def create_school(self, code="SCH701"):
        return self.organization_service.create_organization(
            stable_code=code,
            name="测试大学",
            org_type="SCHOOL",
            dimension="ADMIN",
            validity_from=self.today,
        )

    def test_organization_fact_and_event_commit_together(self):
        school = self.create_school()

        event = HrOutboxEvent.objects.get(
            tenant_id=self.tenant_id,
            event_type=EVENT_ORGANIZATION_CREATED,
        )
        self.assertEqual(event.payload_json["organizationId"], str(school.id))
        self.assertEqual(event.payload_json["eventVersion"], 1)

    @patch(
        "hr_structure.services.organization_change.emit_registered_event",
        side_effect=RuntimeError("outbox unavailable"),
    )
    def test_outbox_failure_rolls_back_organization_fact(self, _emit):
        with self.assertRaisesRegex(RuntimeError, "outbox unavailable"):
            self.create_school()

        self.assertFalse(
            HrOrganization.objects.filter(tenant_id=self.tenant_id).exists()
        )

    def test_position_reservation_state_emits_registered_events(self):
        school = self.create_school()
        catalog = PostCatalogService(self.scope).create_catalog(
            stable_code="PC701",
            name="教师岗",
            category="PROFESSIONAL_TECHNICAL",
            subcategory="TEACHER",
        )
        position_service = PositionService(self.scope, actor="w1-test")
        position = position_service.create_position(
            position_code="P701",
            organization_id=school.id,
            post_catalog_version_id=catalog.versions.first().id,
            max_incumbents=1,
        )
        reservation = position_service.reserve(
            source_domain="hr04",
            source_business_type="proposed_hire",
            source_business_id="PH-701",
            position_id=position.id,
            count=1,
            idempotency_key="hr02-w1-701",
        )
        position_service.commit(reservation.id)

        event_types = set(
            HrOutboxEvent.objects.filter(tenant_id=self.tenant_id).values_list(
                "event_type", flat=True
            )
        )
        self.assertTrue(
            {
                EVENT_POSITION_CREATED,
                EVENT_RESERVATION_HELD,
                EVENT_RESERVATION_COMMITTED,
            }.issubset(event_types)
        )

    def test_staffing_approval_and_reorganization_effective_emit_events(self):
        school = self.create_school()
        staffing_service = StaffingPlanService(self.scope, actor="w1-test")
        plan = staffing_service.create_plan(
            code="PLAN-701",
            name="测试编制",
            plan_year=self.today.year,
            validity_from=self.today,
        )
        staffing_service.add_headcount_line(
            plan_id=plan.id,
            organization_id=school.id,
            staffing_basis="OFFICIAL_ESTABLISHMENT",
            authorized_headcount=100,
        )
        staffing_service.submit(plan)
        staffing_service.approve(plan)

        case = self.organization_service.create_change_case(
            change_type="RENAME_ORG",
            title="学校更名",
            reason="验收",
            requested_effective_date=self.today,
            items=[],
        )
        HrStructureChangeItem.objects.create(
            case_id=case,
            sequence=1,
            entity_type="org",
            entity_id=str(school.id),
            action_type="RENAME_ORG",
            after_payload={"name": "测试大学（新）"},
        )
        reorg_service = ReorganizationService(self.scope, actor="w1-test")
        reorg_service.submit(case)
        reorg_service.approve(case)
        reorg_service.schedule(case)
        effective = reorg_service.execute_effective(case, execution_key="exec-701")

        self.assertEqual(effective.status, "EFFECTIVE")
        event_types = set(
            HrOutboxEvent.objects.filter(tenant_id=self.tenant_id).values_list(
                "event_type", flat=True
            )
        )
        self.assertTrue(
            {
                EVENT_STAFFING_PLAN_APPROVED,
                EVENT_ORGANIZATION_CHANGED,
                EVENT_REORGANIZATION_EFFECTIVE,
            }.issubset(event_types)
        )
