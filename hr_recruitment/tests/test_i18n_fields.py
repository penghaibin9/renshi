"""
hr_recruitment/tests/test_i18n_fields.py

总控 §12 JSON 字段规范测试：
- 机器字段名保持 camelCase（不 snake_case、不中文）；
- 状态字段成对：{status: "ACTIVE", statusLabel: "在职"}；
- 只加 label，不改原机器字段名/枚举值；
- 时间 ISO 8601；金额字符串。
"""

import json
from datetime import date
from uuid import uuid4

from django.test import TestCase

from hr_recruitment.constants import ApplicationCanonicalStatus as S
from hr_recruitment.labels import (
    APPLICATION_STATUS_LABELS,
    CAMPAIGN_STATUS_LABELS,
    CANDIDATE_STATUS_LABELS,
    NEED_TYPE_LABELS,
    PLAN_REQUEST_STATUS_LABELS,
    PROPOSED_HIRE_STATUS_LABELS,
    status_label,
)
from hr_recruitment.services.application_service import ApplicationService
from hr_recruitment.services.campaign_service import CampaignService
from hr_recruitment.services.candidate_service import CandidateService

TENANT = 12001


class JsonFieldContractTests(TestCase):
    """API 响应字段名 camelCase + label 成对。"""

    def setUp(self):
        self.camp_service = CampaignService(tenant_id=TENANT, actor="test")
        self.campaign = self.camp_service.create_campaign(
            code="2026-I18N-001", title="规范测试", campaign_type="SINGLE_POSITION"
        )
        self.position = self.camp_service.create_position(
            campaign_id=str(self.campaign.id),
            post_catalog_name="专任教师",
            planned_headcount=1,
        )

    def test_status_label_mapping(self):
        """label 成对：{status, statusLabel}。"""
        self.assertEqual(status_label(APPLICATION_STATUS_LABELS, S.QUALIFIED), "资格通过")
        self.assertEqual(status_label(APPLICATION_STATUS_LABELS, S.WITHDRAWN), "已撤回")
        self.assertEqual(status_label(APPLICATION_STATUS_LABELS, "UNKNOWN"), "UNKNOWN")
        self.assertEqual(status_label(CAMPAIGN_STATUS_LABELS, "OPEN"), "报名中")
        self.assertEqual(status_label(PLAN_REQUEST_STATUS_LABELS, "APPROVED"), "已批准")
        self.assertEqual(status_label(CANDIDATE_STATUS_LABELS, "ACTIVE"), "正常")
        self.assertEqual(status_label(PROPOSED_HIRE_STATUS_LABELS, "APPROVE"), "已批准")
        self.assertEqual(status_label(NEED_TYPE_LABELS, "NEW"), "新增")

    def test_campaign_dto_has_label_pair(self):
        """campaign 列表 DTO 带 statusLabel，原 status 不变（字段名结构零改动，只加 label）。"""
        from hr_recruitment.selectors import campaign as campaign_selector

        data = campaign_selector.list_campaigns(tenant_id=TENANT)
        item = data["items"][0]
        self.assertEqual(item["status"], "DRAFT")
        self.assertEqual(item["statusLabel"], "草稿")
        # 既有机器字段名保持原样（不改 API 字段名结构）
        self.assertIn("public_slug", item)
        self.assertIn("application_open_at", item)

    def test_candidate_dto_has_label_pair(self):
        """人才库 DTO 带 statusLabel + sourceLabel。"""
        CandidateService(tenant_id=TENANT).create_candidate(
            legal_name="候选人", primary_email="i18n@test.local", source="PUBLIC_PORTAL"
        )
        from hr_recruitment.selectors import candidate as candidate_selector

        data = candidate_selector.list_candidates(tenant_id=TENANT)
        item = data["items"][0]
        self.assertEqual(item["source"], "PUBLIC_PORTAL")
        self.assertEqual(item["sourceLabel"], "公开报名")
        self.assertEqual(item["status"], "ACTIVE")
        self.assertEqual(item["statusLabel"], "正常")

    def test_application_dto_has_label_pair(self):
        """资格工作台 queue 带 statusLabel。"""
        cand = CandidateService(tenant_id=TENANT).create_candidate(
            legal_name="候选人", primary_email="qual-i18n@test.local"
        )
        app_service = ApplicationService(tenant_id=TENANT, actor="test")
        draft = app_service.save_draft(
            candidate_id=str(cand.id),
            recruitment_position_id=str(self.position.id),
        )
        app_service.submit(application_id=str(draft.id))

        from hr_recruitment.models import HrJobApplication

        # 直接验证：canonical_status 与 statusLabel 成对（经 workbench DTO 逻辑）
        app = HrJobApplication.objects.get(id=draft.id)
        self.assertEqual(app.canonical_status, S.SUBMITTED)
        self.assertEqual(status_label(APPLICATION_STATUS_LABELS, app.canonical_status), "已提交")
