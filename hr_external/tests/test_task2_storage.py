"""任务 2 · 文件本体私有存储最小实现测试（总册 §92/00 §34）。

覆盖：
- 上传写私有目录（非 public），元数据 SHA-256/大小/MIME 更新；
- ticket 兑换后流式下载（FileResponse）且动作审计；
- ticket 失效/次数用尽/跨 tenant 下载被拒；
- 私有文件不暴露 /media/ 裸 URL（storage_ref 在私有根目录）。
"""

import hashlib
import os
import shutil
import tempfile

from django.conf import settings
from django.test import TestCase, override_settings

from hr_external.models import HrExternalAuditEvent
from hr_external.services.category_service import CategoryService
from hr_external.services.material_service import (
    MaterialAccessDenied,
    MaterialService,
    TicketInvalid,
)
from hr_external.services.profile_service import ProfileService
from hr_external.services.storage_backends import PrivateFileSystemStorage

_PRIVATE_ROOT = tempfile.mkdtemp(prefix="hr08-private-")
_MEDIA_ROOT = tempfile.mkdtemp(prefix="hr08-media-")


def _cleanup():
    for path in (_PRIVATE_ROOT, _MEDIA_ROOT):
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)


@override_settings(MEDIA_ROOT=_MEDIA_ROOT, HR08_PRIVATE_STORAGE_ROOT=_PRIVATE_ROOT)
class PrivateStorageTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        _cleanup()

    def setUp(self):
        from hr_staff.models import HrPerson

        self.tenant = 101
        CategoryService().ensure_default_categories(self.tenant)
        self.person = HrPerson.objects.create(tenant_id=self.tenant, legal_name="严工")
        self.profile = ProfileService().create_profile(
            tenant_id=self.tenant,
            person_id=self.person.id,
            primary_category_code="INDUSTRY_PROFESSOR",
        )
        self.service = MaterialService()
        self.material = self.service.create_material(
            tenant_id=self.tenant,
            external_profile_id=self.profile.id,
            category="ENTERPRISE_EXPERIENCE",
            title="企业经历证明",
        )
        self.storage = PrivateFileSystemStorage(location=settings.HR08_PRIVATE_STORAGE_ROOT)

    def _upload(self, data: bytes = b"%PDF-1.4 fake pdf content"):
        self.service.save_material_file(
            material=self.material,
            tenant_id=self.tenant,
            content=data,
            original_filename="proof.pdf",
            mime_type="application/pdf",
            storage=self.storage,
        )
        self.material.refresh_from_db()
        return self.material

    def test_upload_writes_private_dir_not_public(self):
        material = self._upload()
        self.assertTrue(self.storage.exists(material.storage_ref))
        absolute = os.path.join(settings.HR08_PRIVATE_STORAGE_ROOT, material.storage_ref)
        self.assertTrue(os.path.isfile(absolute))
        self.assertFalse(os.path.exists(os.path.join(settings.MEDIA_ROOT, material.storage_ref)))
        self.assertEqual(material.size_bytes, len(b"%PDF-1.4 fake pdf content"))
        self.assertEqual(
            material.sha256,
            hashlib.sha256(b"%PDF-1.4 fake pdf content").hexdigest(),
        )

    def test_download_via_ticket_streams_and_audits(self):
        self._upload()
        token = self.service.sign_token(
            tenant_id=self.tenant, material_id=str(self.material.id)
        )
        self.service.issue_ticket(
            tenant_id=self.tenant, material=self.material, purpose="核验", token=token
        )
        authorized_material = self.service.redeem_ticket(
            token=token,
            actor_user_id=1,
            tenant_id=self.tenant,
        )
        stream = self.service.open_authorized_stream(
            authorized_material,
            storage=self.storage,
        )
        self.assertEqual(stream.read(), b"%PDF-1.4 fake pdf content")
        stream.close()
        self.assertTrue(
            HrExternalAuditEvent.objects.filter(
                action="ExternalMaterialDownload",
                business_id=str(self.material.id),
            ).exists()
        )

    def test_ticket_reuse_blocked(self):
        self._upload()
        token = self.service.sign_token(
            tenant_id=self.tenant, material_id=str(self.material.id)
        )
        self.service.issue_ticket(tenant_id=self.tenant, material=self.material, token=token)
        self.service.redeem_ticket(token=token, actor_user_id=1)
        with self.assertRaises(TicketInvalid):
            self.service.redeem_ticket(token=token, actor_user_id=1)

    def test_tampered_token_blocked(self):
        self._upload()
        token = self.service.sign_token(
            tenant_id=self.tenant, material_id=str(self.material.id)
        )
        with self.assertRaises(TicketInvalid):
            self.service.redeem_ticket(token=token[:-4] + "xxxx")

    def test_cross_tenant_blocked(self):
        self._upload()
        token = self.service.sign_token(
            tenant_id=self.tenant, material_id=str(self.material.id)
        )
        self.service.issue_ticket(tenant_id=self.tenant, material=self.material, token=token)
        with self.assertRaises(TicketInvalid):
            self.service.redeem_ticket(token=token, actor_user_id=1, tenant_id=999)

    def test_missing_file_returns_denied(self):
        self.material.refresh_from_db()
        self.assertFalse(self.material.storage_ref)
        with self.assertRaises(MaterialAccessDenied):
            self.service.open_authorized_stream(self.material)
