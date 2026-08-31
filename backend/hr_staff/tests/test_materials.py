"""S8 · MaterialService 测试：版本链不可覆盖、ticket 一次性/短时效、跨 tenant 拒绝、SHA-256。"""

from io import BytesIO

from django.test import TestCase
from django.utils import timezone

from hr_staff.constants import (
    MaterialVersionStatus,
    SensitivityLevel,
)
from hr_staff.models import HrStaffMaterial, HrStaffMaterialVersion
from hr_staff.services.material_service import (
    MaterialAccessDenied,
    MaterialService,
)
from hr_staff.tests.factories import make_person, make_staff

TENANT = 1
OTHER_TENANT = 2


class MaterialServiceTests(TestCase):
    def setUp(self):
        self.staff = make_staff(TENANT, make_person(TENANT, "张某某"), "T001238")
        self.other_staff = make_staff(OTHER_TENANT, make_person(OTHER_TENANT, "李四"), "T000001")
        self.svc = MaterialService(TENANT, actor_user_id=1)

    def test_create_material_with_sha256(self):
        material = self.svc.create_material(
            staff_id=self.staff,
            category_code="EDUCATION",
            title="学历证书",
            storage_file_id="protected/abc.pdf",
            sha256="a" * 64,
            size_bytes=1024,
        )
        version = material.versions.get()
        self.assertEqual(version.status, MaterialVersionStatus.CURRENT)
        self.assertEqual(material.current_version_id, version.id)
        self.assertEqual(material.verification_status, "UNVERIFIED")

    def test_version_chain_never_overwrites(self):
        material = self.svc.create_material(
            staff_id=self.staff,
            category_code="EDUCATION",
            title="学历证书",
            storage_file_id="protected/v1.pdf",
            sha256="1" * 64,
        )
        v2 = self.svc.add_version(
            material_id=material.id,
            storage_file_id="protected/v2.pdf",
            sha256="2" * 64,
        )
        v1 = material.versions.get(version_no=1)
        v1.refresh_from_db()
        self.assertEqual(v1.status, MaterialVersionStatus.REPLACED)
        self.assertEqual(v1.replaced_by_version_id, v2.id)
        material.refresh_from_db()
        self.assertEqual(material.current_version_id, v2.id)

    def test_download_ticket_single_use(self):
        material = self.svc.create_material(
            staff_id=self.staff, category_code="IDENTITY", title="身份证", storage_file_id="protected/id.pdf"
        )
        ticket = self.svc.issue_download_ticket(
            staff_id=self.staff,
            material_id=material.id,
            purpose="核对身份证明",
            permission_ok=True,
            sensitive_ok=True,
        )
        self.assertIn("ticket", ticket)
        self.assertNotIn("/media/", ticket["originalFilename"] or "")
        # DB 票据一次性：第二次消费被拒
        payload = self.svc.consume_download_ticket(ticket["ticket"])
        self.assertIsNotNone(payload)
        from hr_staff.services.material_service import MaterialAccessDenied

        with self.assertRaises(MaterialAccessDenied):
            self.svc.consume_download_ticket(ticket["ticket"])

    def test_download_ticket_requires_purpose_and_permission(self):
        material = self.svc.create_material(
            staff_id=self.staff, category_code="OTHER_HR", title="材料", storage_file_id="f"
        )
        with self.assertRaises(MaterialAccessDenied):
            self.svc.issue_download_ticket(staff_id=self.staff, material_id=material.id, purpose="", permission_ok=True, sensitive_ok=True)
        with self.assertRaises(MaterialAccessDenied):
            self.svc.issue_download_ticket(staff_id=self.staff, material_id=material.id, purpose="x", permission_ok=False, sensitive_ok=True)

    def test_sensitive_material_requires_sensitive_permission(self):
        material = self.svc.create_material(
            staff_id=self.staff,
            category_code="IDENTITY",
            title="身份证",
            storage_file_id="f",
            sensitivity_level=SensitivityLevel.HIGH_SENSITIVE,
        )
        with self.assertRaises(MaterialAccessDenied):
            self.svc.issue_download_ticket(
                staff_id=self.staff, material_id=material.id, purpose="x", permission_ok=True, sensitive_ok=False
            )

    def test_download_ticket_denies_wrong_staff(self):
        """P1-11：票据归属必须与 URL staff 一致。"""
        material = self.svc.create_material(
            staff_id=self.staff, category_code="OTHER_HR", title="材料", storage_file_id="f"
        )
        other = make_staff(TENANT, make_person(TENANT, "赵六"), "T888888")
        with self.assertRaises(MaterialAccessDenied):
            self.svc.issue_download_ticket(
                staff_id=other, material_id=material.id, purpose="x", permission_ok=True, sensitive_ok=True
            )

    def test_cross_tenant_denied(self):
        """A 校服务无法操作 B 校材料（跨 tenant 拒绝）。"""
        material_b = HrStaffMaterial.objects.create(
            tenant_id=OTHER_TENANT,
            staff_id=self.other_staff,
            category_code="OTHER_HR",
            title="B校材料",
        )
        HrStaffMaterialVersion.objects.create(
            tenant_id=OTHER_TENANT,
            material_id=material_b,
            version_no=1,
            storage_file_id="b",
        )
        # A 校用户 + A 校 staff 试图下载 B 校材料 → tenant 过滤拒绝
        with self.assertRaises(MaterialAccessDenied):
            self.svc.issue_download_ticket(
                staff_id=self.staff, material_id=material_b.id, purpose="x", permission_ok=True, sensitive_ok=True
            )
        # A 校用户 + B 校 staff → resolve_staff 跨租户拒绝
        from hr_staff.services.common import CrossTenantReference

        with self.assertRaises(CrossTenantReference):
            self.svc.issue_download_ticket(
                staff_id=self.other_staff, material_id=material_b.id, purpose="x", permission_ok=True, sensitive_ok=True
            )

    def test_no_media_plain_url_in_metadata(self):
        material = self.svc.create_material(
            staff_id=self.staff, category_code="EDUCATION", title="学历", storage_file_id="protected/x.pdf"
        )
        # 存储引用是受控 ID，不是可猜的 /media/ 裸 URL
        version = material.versions.get()
        self.assertFalse(version.storage_file_id.startswith("/media/"))
        self.assertNotIn("MEDIA_URL", version.storage_file_id)
        # API 层（selector）只暴露 original_filename，不暴露 storage_file_id 本身
        from hr_staff.context import HrStaffRequestContext, HrStaffScope
        from hr_staff.selectors.materials import MaterialSelector

        data = MaterialSelector(
            HrStaffRequestContext(tenant_id=TENANT, scope=HrStaffScope(scope_type="SCHOOL"))
        ).list_materials(self.staff.id)
        self.assertNotIn("storage_file_id", data["items"][0])
