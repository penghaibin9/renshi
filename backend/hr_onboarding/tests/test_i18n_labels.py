"""
hr_onboarding/tests/test_i18n_labels.py

前端中文化 + JSON 字段规范回归测试：
- R8-A：API 输出含成对 xxxLabel 中文字段（statusLabel/sourceTypeLabel 等），机器字段名零改动；
- R8-B：labels 模块映射覆盖 HR05 全部枚举，且中文非空；
- R8-C：模板全部可见文案经 {% trans %}（i18n 可提取），不散落硬编码英文。
"""

import os

from django.conf import settings
from django.test import TestCase

from hr_onboarding.api import labels as api_labels


class LabelMappingTests(TestCase):
    def test_status_label_chinese(self):
        self.assertEqual(api_labels.label_for(api_labels.CASE_STATUS_LABELS, "ACTIVE"), "已生效")
        self.assertEqual(api_labels.label_for(api_labels.CASE_STATUS_LABELS, "PROBATION"), "试用期")
        self.assertEqual(api_labels.label_for(api_labels.SOURCE_TYPE_LABELS, "HR04_HIRE"), "招聘录用")

    def test_unknown_returns_raw(self):
        self.assertEqual(api_labels.label_for(api_labels.CASE_STATUS_LABELS, "WEIRD"), "WEIRD")
        self.assertEqual(api_labels.label_for(api_labels.CASE_STATUS_LABELS, None), "")

    def test_all_mappings_nonempty(self):
        for name in (
            "CASE_STATUS_LABELS", "SOURCE_TYPE_LABELS", "EMPLOYMENT_TYPE_LABELS",
            "STAFF_CATEGORY_LABELS", "PERSON_MATCH_LABELS", "ACTIVATION_STATUS_LABELS",
            "VERIFICATION_STATUS_LABELS", "MATERIAL_STATUS_LABELS", "BLOCKING_PHASE_LABELS",
            "REUSE_POLICY_LABELS", "TASK_STATUS_LABELS", "BLOCKING_LEVEL_LABELS",
            "RESPONSIBLE_ROLE_LABELS", "PROVISIONING_STATUS_LABELS", "PROBATION_STATUS_LABELS",
            "PROBATION_RESULT_LABELS",
        ):
            mapping = getattr(api_labels, name)
            self.assertTrue(mapping, name)
            for key, val in mapping.items():
                self.assertTrue(val.strip(), f"{name}[{key}] 中文为空")


class TemplateI18nTests(TestCase):
    """R8-C：模板不得残留硬编码英文可见文案（应走 {% trans %}）。"""

    def _scan(self, path):
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    def test_onboarding_templates_use_trans(self):
        template_root = os.path.join(settings.FRONTEND_DIR, "templates", "hr", "onboarding")
        self.assertTrue(os.path.isdir(template_root))
        scanned = 0
        for dirpath, _, files in os.walk(template_root):
            for fname in files:
                if not fname.endswith(".html"):
                    continue
                path = os.path.join(dirpath, fname)
                content = self._scan(path)
                scanned += 1
                # 标题/表头等可见英文不应裸写（允许 status 枚举值与 aria 等属性值）
                for token in ("Case", "Person", "Status:", "Submit", "Loading", "Error"):
                    self.assertNotIn(f">{token}", content, f"{path} 含硬编码英文可见文案: {token}")
        self.assertGreaterEqual(scanned, 20, "HR05 应有 20+ 个模板")


class LabelInApiTests(TestCase):
    """R8-A：selectors 输出含 xxxLabel 成对字段，机器字段名未改名。"""

    def test_list_cases_has_labels(self):
        from hr_onboarding.api import selectors
        from hr_onboarding.services.case_service import CaseService

        import uuid as _uuid

        service = CaseService(tenant_id=1)
        service.create_case_from_handoff(
            {
                "source_type": "HR04_HIRE",
                "source_id": f"ph-{_uuid.uuid4().hex}",
                "legal_name": "测试",
            },
            idempotency_key=f"k-i18n-case-{_uuid.uuid4().hex}",
        )
        data = selectors.list_cases(tenant_id=1)
        item = data["items"][0]
        self.assertIn("statusLabel", item)
        self.assertIn("sourceTypeLabel", item)
        self.assertIn("status", item)  # 机器字段保留
        self.assertNotIn("caseNo", item)  # 未改名为 camelCase（保持现状）
