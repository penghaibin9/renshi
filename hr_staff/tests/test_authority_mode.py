"""S12 · Authority 模式守卫测试：AUTHORITY 后禁 fallback、未切换拒绝权威读。"""

from types import SimpleNamespace
from unittest import mock

from django.test import TestCase

from hr_staff.constants import AuthorityMode
from hr_staff.services.authority_mode_service import AuthorityModeError, AuthorityModeService

TENANT = 1


class _FakeCutoverModel:
    """假 cutover 模型（迷你环境无 hr_control_center）。"""

    instance = None

    @classmethod
    def reset(cls, instance=None):
        cls.instance = instance

    @classmethod
    def objects_filter_first(cls, tenant_id, domain):
        return cls.instance


class AuthorityModeServiceTests(TestCase):
    def setUp(self):
        self.svc = AuthorityModeService()

    def _patch_model(self, mode=None):
        _FakeCutoverModel.reset(SimpleNamespace(mode=mode) if mode else None)
        return mock.patch.object(
            AuthorityModeService,
            "_cutover_model",
            return_value=SimpleNamespace(
                objects=SimpleNamespace(
                    filter=lambda tenant_id, domain: SimpleNamespace(
                        first=lambda: _FakeCutoverModel.objects_filter_first(tenant_id, domain)
                    ),
                    update_or_create=lambda tenant_id, domain, defaults: None,
                )
            ),
        )

    def test_default_legacy_mode(self):
        with self._patch_model(mode=None):
            self.assertEqual(self.svc.get_mode(TENANT), AuthorityMode.LEGACY_STAFF_ONLY)

    def test_authority_mode_read(self):
        with self._patch_model(mode=AuthorityMode.HR03_AUTHORITY):
            self.assertEqual(self.svc.get_mode(TENANT), AuthorityMode.HR03_AUTHORITY)

    def test_require_authority_rejects_when_not_cutover(self):
        with self._patch_model(mode=None):
            with self.assertRaises(AuthorityModeError):
                self.svc.assert_authority_available(TENANT, require_authority=True)

    def test_require_authority_passes_after_cutover(self):
        with self._patch_model(mode=AuthorityMode.HR03_AUTHORITY):
            mode = self.svc.assert_authority_available(TENANT, require_authority=True)
            self.assertEqual(mode, AuthorityMode.HR03_AUTHORITY)
