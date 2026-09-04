"""
hr_onboarding/tests/test_production_r6.py

HR05 生产级审计（第六轮）回归测试：
- R6-A：权限 meta migration 存在（hr05.* 权限可注册）；
- R6-B：会话管理写接口保留 CSRF，只有独立 token 门户免 CSRF；
- R6-C：bank_json 加密存储（不含明文卡号）；
- R6-G：报到时间拒绝未来日期。
"""

from datetime import date, datetime, timedelta, timezone

from django.test import TestCase

from hr_onboarding.api import views as api_views
from hr_onboarding.api import materials as materials_views
from hr_onboarding.api import portal as portal_views
from hr_onboarding.api import probations as probations_views
from hr_onboarding.api import tasks as tasks_views
from hr_onboarding.constants import CaseStatus
from hr_onboarding.models import HrOnboardingCase
from hr_onboarding.services.case_service import CaseService
from hr_onboarding.services.report_service import ReportService

from .test_s3 import _handoff_request


def _case():
    import uuid as _uuid

    service = CaseService(tenant_id=1)
    r = service.create_case_from_handoff(
        _handoff_request(idem_key=f"k-r6-handoff-{_uuid.uuid4().hex}"),
        idempotency_key=f"k-r6-case-{_uuid.uuid4().hex}",
    )
    return HrOnboardingCase.objects.get(id=r["case_id"])


class PermissionMetaMigrationTests(TestCase):
    def test_permission_meta_migration_exists(self):
        """R6-A：0006 迁移必须注册 HrOnboardingPermissionMeta（否则 hr05.* 权限永不进 auth_permission）。"""
        import os

        from django.conf import settings

        migration_path = os.path.join(
            settings.BASE_DIR, "hr_onboarding", "migrations", "0006_hronboardingpermissionmeta.py"
        )
        self.assertTrue(os.path.exists(migration_path))
        with open(migration_path, encoding="utf-8") as fh:
            content = fh.read()
        self.assertIn("HrOnboardingPermissionMeta", content)
        self.assertIn("hr05.case.activate", content)
        self.assertIn("hr05.probation.finalize", content)


class CsrfProtectionTests(TestCase):
    """R6-B：高权限会话写接口必须受 CSRF 保护。"""

    def test_management_post_views_are_csrf_protected(self):
        for v in (
            api_views.hr05_case_activate,
            api_views.hr05_case_report,
            api_views.hr05_case_confirm_intent,
            api_views.hr05_case_request_delay,
            api_views.hr05_case_decline,
            materials_views.material_submit,
            materials_views.material_verify,
            materials_views.material_return,
            materials_views.material_waive,
            materials_views.material_download_ticket,
            tasks_views.task_start,
            tasks_views.task_complete,
            tasks_views.task_waive,
            tasks_views.provisioning_request,
            tasks_views.provisioning_retry,
            probations_views.probation_open,
            probations_views.probation_submit_review,
            probations_views.probation_confirm,
            probations_views.probation_extend,
            probations_views.probation_fail,
        ):
            self.assertFalse(
                getattr(v, "csrf_exempt", False),
                f"{v.__name__} must remain behind global CSRF middleware",
            )

    def test_token_portal_post_views_are_csrf_exempt(self):
        for view in (
            portal_views.prehire_update_profile,
            portal_views.prehire_confirm_intent,
        ):
            self.assertTrue(getattr(view, "csrf_exempt", False), view.__name__)


class BankEncryptionTests(TestCase):
    def test_bank_json_encrypted(self):
        """R6-C：Portal 提交 bank 数据加密存储，不含明文卡号。"""
        from hr_onboarding.services import portal_service, token_service

        service = CaseService(tenant_id=1)
        r = service.create_case_from_handoff(
            _handoff_request(idem_key="k-r6-bank-h"), idempotency_key="k-r6-bank-c"
        )
        case = HrOnboardingCase.objects.get(id=r["case_id"])
        portal = token_service.resolve_portal_access(tenant_id=None, token=r["portal_token"])
        portal_service.update_profile(
            portal, {"bank": {"account_number": "6222020202020202020", "bank_name": "ICBC"}}
        )
        case.refresh_from_db()
        bank = case.prehire_profile.bank_json
        # 密文存储：不含明文卡号；带加密标记
        self.assertNotIn("6222020202020202020", str(bank))
        self.assertIn("__hr05_enc__", bank)

        # 可解密
        from hr_onboarding.services.security import decrypt_sensitive_value

        decrypted = decrypt_sensitive_value(bank)
        self.assertEqual(decrypted["account_number"], "6222020202020202020")


class ReportFutureDateTests(TestCase):
    def test_report_rejects_future(self):
        """R6-G：实际报到时间晚于当前+1天 → 拒绝。"""
        from hr_onboarding.api.exceptions import InvalidStateTransitionError

        service = CaseService(tenant_id=1)
        r = service.create_case_from_handoff(
            _handoff_request(idem_key="k-r6-future-h"), idempotency_key="k-r6-future-c"
        )
        case = HrOnboardingCase.objects.get(id=r["case_id"])
        service.confirm_intent(case)
        service._transition_locked(case, CaseStatus.READY_TO_REPORT, "TEST", "测试")

        future = datetime.now(timezone.utc) + timedelta(days=10)
        with self.assertRaises(InvalidStateTransitionError):
            ReportService(tenant_id=1).confirm_report(case, actual_report_at=future)

        # 过去时间正常
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        checkin = ReportService(tenant_id=1, actor_user_id=1).confirm_report(
            case, actual_report_at=past
        )
        self.assertIsNotNone(checkin.id)
