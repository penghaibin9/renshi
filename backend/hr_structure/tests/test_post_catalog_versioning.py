"""HR02 岗位目录版本必须完整继承且按生效日留史。"""

from datetime import date
from decimal import Decimal

from django.test import TestCase

from hr_structure.models import HrPostCatalogVersion
from hr_structure.scope import Hr02Scope
from hr_structure.selectors.effective import post_catalog_version_as_of
from hr_structure.services.post_catalog import PostCatalogService


class PostCatalogVersioningTests(TestCase):
    def setUp(self):
        self.scope = Hr02Scope("SCHOOL", tenant_id=920)
        self.service = PostCatalogService(self.scope, actor="catalog-test")

    def test_new_version_closes_old_interval_and_inherits_semantics(self):
        catalog = self.service.create_catalog(
            stable_code="TEACHER-920",
            name="教师岗",
            category=HrPostCatalogVersion.Category.PROFESSIONAL_TECHNICAL,
            subcategory=HrPostCatalogVersion.Subcategory.TEACHER,
            validity_from=date(2025, 1, 1),
            control_mode=HrPostCatalogVersion.ControlMode.POSITION_CONTROL,
            standard_fte=Decimal("0.80"),
            time_type=HrPostCatalogVersion.TimeType.BOTH,
            worker_types_json=["REGULAR", "EXTERNAL"],
            responsibilities_text="教学与科研",
            qualification_rule_json={"credential": "TEACHER"},
            requires_professional_credential=True,
        )

        current = self.service.new_version(
            catalog,
            name="教师岗（2026）",
            validity_from=date(2026, 1, 1),
        )

        previous = catalog.versions.get(version_no=1)
        self.assertEqual(previous.validity_to, date(2026, 1, 1))
        self.assertEqual(current.standard_fte, Decimal("0.80"))
        self.assertEqual(current.time_type, HrPostCatalogVersion.TimeType.BOTH)
        self.assertEqual(current.worker_types_json, ["REGULAR", "EXTERNAL"])
        self.assertTrue(current.requires_professional_credential)
        self.assertEqual(
            post_catalog_version_as_of(920, catalog.id, date(2025, 12, 31)).id,
            previous.id,
        )
        self.assertEqual(
            post_catalog_version_as_of(920, catalog.id, date(2026, 1, 1)).id,
            current.id,
        )

    def test_new_version_rejects_cross_tenant_catalog(self):
        foreign = PostCatalogService(Hr02Scope("SCHOOL", tenant_id=921)).create_catalog(
            stable_code="FOREIGN-921",
            name="外校岗位",
            category=HrPostCatalogVersion.Category.MANAGEMENT,
            validity_from=date(2025, 1, 1),
        )
        with self.assertRaisesRegex(ValueError, "跨租户"):
            self.service.new_version(
                foreign, name="不应成功", validity_from=date(2026, 1, 1)
            )
