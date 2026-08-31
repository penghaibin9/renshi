"""HR02 reorganization execution contracts and effective-dated history."""

from datetime import date, timedelta
from pathlib import Path

from django.test import SimpleTestCase, TestCase

from hr_structure.models import (
    HrOrganization,
    HrOrganizationRelation,
    HrOrganizationVersion,
    HrPosition,
    HrPositionVersion,
    HrPostCatalog,
    HrPostCatalogVersion,
    HrStructureChangeCase,
    HrStructureChangeItem,
)
from hr_structure.scope import Hr02Scope
from hr_structure.selectors.effective import org_version_as_of, position_as_of
from hr_structure.services.reorganization import ReorgServiceError, ReorganizationService


class ReorganizationApplyStaticContractTests(SimpleTestCase):
    def test_supported_actions_are_not_left_in_placeholder_branch(self):
        source = (
            Path(__file__).parents[1] / "services" / "reorganization.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("暂未实现落地", source)
        for action in (
            'action == "CREATE_ORG"',
            'action == "REPARENT_ORG"',
            'action == "MOVE_POSITION"',
            'action == "CREATE_POSITION"',
            'action == "CLOSE_POSITION"',
        ):
            self.assertIn(action, source)
        self.assertIn("REORG_MAPPING_CONTRACT_UNAVAILABLE", source)
        self.assertIn("errorCode", source)


class ReorganizationApplyActionTests(TestCase):
    tenant_id = 802

    def setUp(self):
        self.today = date.today()
        self.scope = Hr02Scope("SCHOOL", tenant_id=self.tenant_id)
        self.service = ReorganizationService(self.scope, actor="reorg-test")
        self.school = self._org("SCH-802", "测试大学", "SCHOOL", None)
        self.parent_a = self._org("A-802", "甲学院", "COLLEGE", self.school.id)
        self.parent_b = self._org("B-802", "乙学院", "COLLEGE", self.school.id)
        self.child = self._org("C-802", "系部", "DEPARTMENT", self.parent_a.id)
        self.catalog = HrPostCatalog.objects.create(
            tenant_id=self.tenant_id, stable_code="CAT-802"
        )
        self.catalog_version = HrPostCatalogVersion.objects.create(
            catalog_id=self.catalog,
            tenant_id=self.tenant_id,
            name="教师岗",
            validity_from=self.today - timedelta(days=30),
            status=HrPostCatalogVersion.Status.ACTIVE,
        )

    def _org(self, code, name, org_type, parent_id):
        org = HrOrganization.objects.create(
            tenant_id=self.tenant_id,
            stable_code=code,
            org_dimension=HrOrganization.Dimension.ADMIN,
        )
        HrOrganizationVersion.objects.create(
            organization_id=org,
            tenant_id=self.tenant_id,
            name=name,
            org_type=org_type,
            parent_organization_id_id=parent_id,
            validity_from=self.today - timedelta(days=30),
            status=HrOrganizationVersion.Status.EFFECTIVE,
        )
        if parent_id:
            HrOrganizationRelation.objects.create(
                tenant_id=self.tenant_id,
                source_org_id=org,
                target_org_id_id=parent_id,
                relation_type=HrOrganizationRelation.RelationType.ADMIN_PARENT,
                validity_from=self.today - timedelta(days=30),
            )
        return org

    def _case(self, number, effective_date=None, status=None):
        return HrStructureChangeCase.objects.create(
            tenant_id=self.tenant_id,
            case_no=number,
            change_type="REPARENT_ORG",
            title=number,
            requested_effective_date=effective_date or self.today,
            status=status or HrStructureChangeCase.Status.SCHEDULED,
        )

    def _item(self, case, sequence, action, entity_type, entity_id="", payload=None):
        return HrStructureChangeItem.objects.create(
            case_id=case,
            sequence=sequence,
            entity_type=entity_type,
            entity_id=str(entity_id),
            action_type=action,
            after_payload=payload or {},
        )

    def test_create_org_and_position_are_real_idempotent_facts(self):
        case = self._case("REORG-CREATE-802")
        org_item = self._item(
            case,
            1,
            "CREATE_ORG",
            "org",
            payload={
                "stableCode": "NEW-802",
                "name": "新建部门",
                "orgType": "DEPARTMENT",
                "dimension": "ADMIN",
                "parentOrganizationId": self.school.id,
            },
        )
        position_item = self._item(
            case,
            2,
            "CREATE_POSITION",
            "position",
            payload={
                "positionCode": "POS-NEW-802",
                "organizationId": self.parent_a.id,
                "postCatalogVersionId": self.catalog_version.id,
                "plannedFte": "1.00",
                "maxIncumbents": 1,
            },
        )

        effective = self.service.execute_effective(case, "exec-create-802")
        self.assertEqual(effective.status, HrStructureChangeCase.Status.EFFECTIVE)
        org = HrOrganization.objects.get(tenant_id=self.tenant_id, stable_code="NEW-802")
        position = HrPosition.objects.get(
            tenant_id=self.tenant_id, position_code="POS-NEW-802"
        )
        self.assertEqual(org.versions.get().change_case_id, case.case_no)
        self.assertEqual(position.history_versions.count(), 1)
        org_item.refresh_from_db()
        position_item.refresh_from_db()
        self.assertEqual(org_item.entity_id, str(org.id))
        self.assertEqual(position_item.entity_id, str(position.id))
        self.service.execute_effective(case, "exec-create-802")
        self.assertEqual(
            HrOrganization.objects.filter(
                tenant_id=self.tenant_id, stable_code="NEW-802"
            ).count(),
            1,
        )

    def test_reparent_appends_org_version_and_relation_history(self):
        case = self._case("REORG-REPARENT-802")
        self._item(
            case,
            1,
            "REPARENT_ORG",
            "org",
            self.child.id,
            {"targetParentId": self.parent_b.id},
        )
        effective = self.service.execute_effective(case, "exec-reparent-802")
        self.assertEqual(effective.status, HrStructureChangeCase.Status.EFFECTIVE)
        before = org_version_as_of(
            self.tenant_id, self.child.id, self.today - timedelta(days=1)
        )
        after = org_version_as_of(self.tenant_id, self.child.id, self.today)
        self.assertEqual(before.parent_organization_id_id, self.parent_a.id)
        self.assertEqual(after.parent_organization_id_id, self.parent_b.id)
        self.assertEqual(after.version_no, 2)
        relations = HrOrganizationRelation.objects.filter(
            tenant_id=self.tenant_id,
            source_org_id=self.child.id,
            relation_type=HrOrganizationRelation.RelationType.ADMIN_PARENT,
        ).order_by("validity_from")
        self.assertEqual(relations.count(), 2)
        self.assertEqual(relations.last().target_org_id_id, self.parent_b.id)

    def test_move_then_close_position_preserves_as_of_history(self):
        position = HrPosition.objects.create(
            tenant_id=self.tenant_id,
            position_code="POS-MOVE-802",
            organization_id=self.parent_a,
            post_catalog_version_id=self.catalog_version,
            validity_from=self.today - timedelta(days=20),
            lifecycle_status=HrPosition.LifecycleStatus.ACTIVE,
        )
        move_date = self.today - timedelta(days=1)
        move_case = self._case("REORG-MOVE-802", move_date)
        self._item(
            move_case,
            1,
            "MOVE_POSITION",
            "position",
            position.id,
            {"targetOrganizationId": self.parent_b.id},
        )
        moved = self.service.execute_effective(move_case, "exec-move-802")
        self.assertEqual(moved.status, HrStructureChangeCase.Status.EFFECTIVE)
        self.assertEqual(
            position_as_of(
                self.tenant_id, position.id, move_date - timedelta(days=1)
            ).organization_id_id,
            self.parent_a.id,
        )
        self.assertEqual(
            position_as_of(self.tenant_id, position.id, move_date).organization_id_id,
            self.parent_b.id,
        )

        close_case = self._case("REORG-CLOSE-802", self.today)
        self._item(
            close_case,
            1,
            "CLOSE_POSITION",
            "position",
            position.id,
            {"closeReason": "岗位撤销"},
        )
        closed = self.service.execute_effective(close_case, "exec-close-802")
        self.assertEqual(closed.status, HrStructureChangeCase.Status.EFFECTIVE)
        position.refresh_from_db()
        self.assertEqual(position.lifecycle_status, HrPosition.LifecycleStatus.CLOSED)
        self.assertEqual(position.history_versions.count(), 3)
        self.assertEqual(
            position_as_of(self.tenant_id, position.id, self.today).lifecycle_status,
            HrPosition.LifecycleStatus.CLOSED,
        )

    def test_missing_payload_and_merge_split_are_stable_submit_blockers(self):
        missing = self._case(
            "REORG-MISSING-802", status=HrStructureChangeCase.Status.DRAFT
        )
        self._item(missing, 1, "CREATE_POSITION", "position", payload={})
        impact = self.service.impact_analysis(missing)
        codes = {row["code"] for row in impact["checks"]}
        self.assertIn("CREATE_POSITION_CODE_REQUIRED", codes)
        with self.assertRaises(ReorgServiceError) as error:
            self.service.submit(missing)
        self.assertEqual(error.exception.code, "HR02_REORG_HAS_BLOCKERS")

        merge = self._case(
            "REORG-MERGE-802", status=HrStructureChangeCase.Status.DRAFT
        )
        self._item(merge, 1, "MERGE_ORGS", "org", self.parent_a.id, {})
        impact = self.service.impact_analysis(merge)
        self.assertIn(
            "REORG_MAPPING_CONTRACT_UNAVAILABLE",
            {row["code"] for row in impact["checks"]},
        )

    def test_late_failure_rolls_back_all_prior_items(self):
        case = self._case("REORG-ROLLBACK-802")
        self._item(
            case,
            1,
            "CREATE_ORG",
            "org",
            payload={
                "stableCode": "ROLLBACK-802",
                "name": "不应残留",
                "orgType": "DEPARTMENT",
                "dimension": "ADMIN",
                "parentOrganizationId": self.school.id,
            },
        )
        self._item(case, 2, "RENAME_ORG", "org", "not-an-id", {"name": "失败"})
        result = self.service.execute_effective(case, "exec-rollback-802")
        self.assertEqual(result.status, HrStructureChangeCase.Status.FAILED_EFFECT)
        self.assertEqual(
            result.execution_result_json["errorCode"], "REORG_ENTITY_ID_REQUIRED"
        )
        self.assertFalse(
            HrOrganization.objects.filter(
                tenant_id=self.tenant_id, stable_code="ROLLBACK-802"
            ).exists()
        )
        self.assertFalse(
            HrPositionVersion.objects.filter(
                tenant_id=self.tenant_id, change_case_id=case.case_no
            ).exists()
        )
