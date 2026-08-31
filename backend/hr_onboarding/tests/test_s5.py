"""
hr_onboarding/tests/test_s5.py

HR05-S3/S5 材料核验测试：
- 按模板实例化材料清单（幂等）；
- 提交材料（文件走私有存储，mock store）；
- 核验记录 reviewer/evidence/reason；
- RETURNED 可重提；HR04 REQUIRE_ORIGINAL 拒绝复用；WAIVED 必须 reason。
"""

from datetime import datetime, timezone
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from hr_onboarding.api.exceptions import Hr05ApiError
from hr_onboarding.constants import MaterialStatus, VerificationResult
from hr_onboarding.models import (
    HrMaterialVerification,
    HrOnboardingCase,
    HrOnboardingMaterial,
    HrOnboardingMaterialRequirement,
)
from hr_onboarding.services.case_service import CaseService
from hr_onboarding.services.material_service import MaterialService, ensure_materials_from_requirements

from .test_s3 import _handoff_request
from .test_models_s2 import _build_template

TZ = timezone.utc


class MaterialServiceTests(TestCase):
    def setUp(self):
        import uuid as _uuid

        _, self.version, _ = _build_template(tenant_id=1)
        self.case_service = CaseService(tenant_id=1)
        r = self.case_service.create_case_from_handoff(
            _handoff_request(idem_key=f"k-s5-handoff-{_uuid.uuid4().hex}"),
            idempotency_key=f"k-s5-case-{_uuid.uuid4().hex}",
        )
        self.case = HrOnboardingCase.objects.get(id=r["case_id"])
        # 绑定模板版本（S3 手建 case 默认无模板；S4/S5 起模板由 HR 指定）
        self.case.template_version_id = self.version.id
        self.case.save(update_fields=["template_version_id"])
        self.req = HrOnboardingMaterialRequirement.objects.filter(
            tenant_id=1, template_version=self.version
        ).first()
        self.service = MaterialService(tenant_id=1, actor_user_id=9)

    def test_ensure_materials_idempotent(self):
        n1 = ensure_materials_from_requirements(self.case)
        n2 = ensure_materials_from_requirements(self.case)
        self.assertEqual(n1, 1)
        self.assertEqual(n2, 0)
        self.assertEqual(
            HrOnboardingMaterial.objects.filter(case=self.case).count(), 1
        )

    def test_submit_material_private_storage(self):
        ensure_materials_from_requirements(self.case)
        material = HrOnboardingMaterial.objects.get(case=self.case)
        with mock.patch(
            "hr_onboarding.services.material_service.store_material_file"
        ) as mock_store:
            mock_store.return_value = {
                "file_version_id": "11111111-2222-3333-4444-555555555555",
                "original_name": "idcard.pdf",
                "ext": "pdf",
                "size": 100,
                "sha256": "abc",
                "mime": "application/pdf",
            }
            uploaded = SimpleUploadedFile("idcard.pdf", b"%PDF-1.4 fake", content_type="application/pdf")
            updated = self.service.submit_material(self.case, self.req.id, uploaded)

        mock_store.assert_called_once()
        self.assertEqual(updated.status, "UNDER_REVIEW")  # verification_required=True
        self.assertEqual(updated.file_meta_json["sha256"], "abc")
        # storage_path 不持久化（防内部路径泄漏）；file_version_id 保留
        self.assertNotIn("storage_path", updated.file_meta_json)
        self.assertIn("file_version_id", updated.file_meta_json)
    def test_verify_records_reviewer_and_evidence(self):
        ensure_materials_from_requirements(self.case)
        material = HrOnboardingMaterial.objects.get(case=self.case)
        material.status = MaterialStatus.UNDER_REVIEW
        material.save(update_fields=["status"])

        updated = self.service.verify_material(
            material,
            result=VerificationResult.VERIFIED,
            reason="与原件一致",
            evidence={"evidence": "证件核验通过"},
        )
        self.assertEqual(updated.status, MaterialStatus.VERIFIED)
        v = HrMaterialVerification.objects.get(material=material)
        self.assertEqual(v.reviewer_id, 9)
        self.assertEqual(v.evidence_snapshot, {"evidence": "证件核验通过"})

    def test_verify_rejects_wrong_status(self):
        material = HrOnboardingMaterial.objects.create(
            tenant_id=1, case=self.case, requirement=self.req, status=MaterialStatus.MISSING
        )
        with self.assertRaises(Hr05ApiError):
            self.service.verify_material(material, result=VerificationResult.VERIFIED)

    def test_return_then_resubmit(self):
        material = HrOnboardingMaterial.objects.create(
            tenant_id=1, case=self.case, requirement=self.req, status=MaterialStatus.UNDER_REVIEW
        )
        returned = self.service.return_material(material, reason="模糊")
        self.assertEqual(returned.status, MaterialStatus.RETURNED)

        # 重新提交（mock store）→ 回到 UNDER_REVIEW
        with mock.patch(
            "hr_onboarding.services.material_service.store_material_file"
        ) as mock_store:
            mock_store.return_value = {
                "file_version_id": "11111111-2222-3333-4444-555555555555",
                "original_name": "idcard2.pdf",
                "ext": "pdf",
                "size": 200,
                "sha256": "def",
                "mime": "application/pdf",
            }
            uploaded = SimpleUploadedFile("idcard2.pdf", b"%PDF-1.4 fake2", content_type="application/pdf")
            resubmitted = self.service.submit_material(self.case, self.req.id, uploaded)
        self.assertEqual(resubmitted.status, MaterialStatus.UNDER_REVIEW)

    def test_hr04_require_original_rejected(self):
        """REQUIRE_ORIGINAL 的 HR04 材料不可直接复用。"""
        ensure_materials_from_requirements(self.case)
        material = HrOnboardingMaterial.objects.get(case=self.case)
        material.source = "HR04"
        material.save(update_fields=["source"])
        self.req.reuse_policy = "REQUIRE_ORIGINAL"
        self.req.save(update_fields=["reuse_policy"])

        with mock.patch("hr_onboarding.services.material_service.store_material_file"):
            uploaded = SimpleUploadedFile("idcard.pdf", b"%PDF-1.4", content_type="application/pdf")
            with self.assertRaises(Hr05ApiError):
                self.service.submit_material(self.case, self.req.id, uploaded)

    def test_waive_requires_reason(self):
        material = HrOnboardingMaterial.objects.create(
            tenant_id=1, case=self.case, requirement=self.req, status=MaterialStatus.MISSING
        )
        with self.assertRaises(Hr05ApiError):
            self.service.waive_material(material, reason="")
        waived = self.service.waive_material(material, reason="学校政策豁免")
        self.assertEqual(waived.status, MaterialStatus.WAIVED)

    def test_submit_enforces_allowed_formats(self):
        """格式白名单：非白名单扩展名提交被拒（不经 mock store）。"""
        from hr_onboarding.services import file_service

        self.req.allowed_formats = ["pdf"]
        self.req.save(update_fields=["allowed_formats"])
        with self.assertRaises(ValueError):
            file_service.validate_upload(
                SimpleUploadedFile("malware.exe", b"MZ", content_type="application/x-msdownload"),
                allowed_formats=["pdf"],
            )
        # 白名单内通过
        meta = file_service.validate_upload(
            SimpleUploadedFile("doc.pdf", b"%PDF", content_type="application/pdf"),
            allowed_formats=["pdf"],
        )
        self.assertEqual(meta["ext"], "pdf")

    def test_double_extension_rejected(self):
        from hr_onboarding.services import file_service

        with self.assertRaises(ValueError):
            file_service.validate_upload(
                SimpleUploadedFile("doc.pdf.html", b"<script>", content_type="text/html")
            )
