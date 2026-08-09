"""
hr_recruitment/tests/test_candidate_s5.py

HR04-03 候选人/申请 + 公开门户（S5）测试：
- Candidate 与 Application 分离（一个候选多申请）；
- 身份去重 EXACT/POSSIBLE/NO_MATCH（绝不自动 merge）；
- 申请提交幂等（active 唯一约束）；
- 提交冻结版本 + 写 ledger；
- 撤回（WITHDRAWN）后可重新申请；
- 公开门户 token 解析学校（禁 tenant_id）；
- 候选 self scope（只返回本人申请）。
"""

import json

from datetime import date
from uuid import uuid4

from django.test import TestCase
from django.urls import reverse

from hr_recruitment.constants import ApplicationCanonicalStatus as S
from hr_recruitment.models import (
    HrApplicationTransition,
    HrJobApplication,
    HrRecruitmentCandidate,
)
from hr_recruitment.services.application_service import ApplicationService
from hr_recruitment.services.campaign_service import CampaignService
from hr_recruitment.services.candidate_service import CandidateService

TENANT = 4001


class CandidateServiceTests(TestCase):
    def setUp(self):
        self.service = CandidateService(tenant_id=TENANT, actor="test")
        self.candidate = self.service.create_candidate(
            legal_name="张三", primary_email="zhangsan@test.local"
        )

    def test_candidate_uid_immutable_unique(self):
        self.assertTrue(self.candidate.candidate_uid)
        other = self.service.create_candidate(legal_name="李四")
        self.assertNotEqual(self.candidate.candidate_uid, other.candidate_uid)

    def test_identity_match_by_email_possible(self):
        result = self.service.identity_match(primary_email="ZHANGSAN@test.local")
        self.assertEqual(result["match_result"], "POSSIBLE_MATCH")
        self.assertEqual(len(result["matches"]), 1)
        self.assertFalse(result["auto_merge"])

    def test_identity_match_no_match(self):
        result = self.service.identity_match(primary_email="nobody@test.local")
        self.assertEqual(result["match_result"], "NO_MATCH")

    def test_identity_match_by_identity_hash_exact(self):
        c = self.service.create_candidate(
            legal_name="王五", primary_email="wangwu@test.local", national_id="110101199001011234"
        )
        result = self.service.identity_match(national_id="110101199001011234")
        self.assertEqual(result["match_result"], "EXACT_MATCH")
        self.assertEqual(len(result["matches"]), 1)
        self.assertEqual(result["matches"][0]["id"], str(c.id))


class ApplicationServiceTests(TestCase):
    def setUp(self):
        self.camp_service = CampaignService(tenant_id=TENANT, actor="test")
        self.campaign = self.camp_service.create_campaign(
            code="2026-S5-001", title="S5 招聘", campaign_type="SINGLE_POSITION"
        )
        self.position = self.camp_service.create_position(
            campaign_id=str(self.campaign.id),
            post_catalog_name="S5 专任教师",
            planned_headcount=1,
        )
        self.candidate_service = CandidateService(tenant_id=TENANT)
        self.candidate = self.candidate_service.create_candidate(
            legal_name="张三", primary_email="z@test.local"
        )
        self.app_service = ApplicationService(tenant_id=TENANT, actor="test")

    def test_draft_then_submit_with_application_no(self):
        draft = self.app_service.save_draft(
            candidate_id=str(self.candidate.id),
            recruitment_position_id=str(self.position.id),
            form_data={"education": "博士"},
        )
        self.assertEqual(draft.canonical_status, S.DRAFT)
        app = self.app_service.submit(application_id=str(draft.id))
        self.assertEqual(app.canonical_status, S.SUBMITTED)
        self.assertTrue(app.application_no)
        self.assertTrue(app.submitted_at)

    def test_submit_is_idempotent(self):
        draft = self.app_service.save_draft(
            candidate_id=str(self.candidate.id),
            recruitment_position_id=str(self.position.id),
        )
        app1 = self.app_service.submit(application_id=str(draft.id))
        app2 = self.app_service.submit(application_id=str(draft.id))
        self.assertEqual(str(app1.id), str(app2.id))
        self.assertEqual(app2.application_no, app1.application_no)

    def test_submit_writes_ledger(self):
        draft = self.app_service.save_draft(
            candidate_id=str(self.candidate.id),
            recruitment_position_id=str(self.position.id),
        )
        self.app_service.submit(application_id=str(draft.id))
        ledger = HrApplicationTransition.objects.filter(
            application_id_id=draft.id, to_status=S.SUBMITTED
        )
        self.assertEqual(ledger.count(), 1)
        self.assertEqual(ledger.first().from_status, S.DRAFT)

    def test_withdraw_then_resubmit(self):
        draft = self.app_service.save_draft(
            candidate_id=str(self.candidate.id),
            recruitment_position_id=str(self.position.id),
        )
        app = self.app_service.submit(application_id=str(draft.id))
        self.app_service.withdraw(application_id=str(app.id))
        app.refresh_from_db()
        self.assertEqual(app.canonical_status, S.WITHDRAWN)
        self.assertFalse(app.is_active)
        # 撤回后可重新申请
        draft2 = self.app_service.save_draft(
            candidate_id=str(self.candidate.id),
            recruitment_position_id=str(self.position.id),
        )
        app2 = self.app_service.submit(application_id=str(draft2.id))
        self.assertNotEqual(str(app.id), str(app2.id))

    def test_duplicate_active_application_raises(self):
        """同候选同岗位同 active 唯一约束。"""
        from django.db import IntegrityError

        draft = self.app_service.save_draft(
            candidate_id=str(self.candidate.id),
            recruitment_position_id=str(self.position.id),
        )
        self.app_service.submit(application_id=str(draft.id))
        # 直接创建第二个 active 申请会违反唯一约束
        with self.assertRaises(IntegrityError):
            HrJobApplication.objects.create(
                tenant_id=TENANT,
                candidate_id=self.candidate,
                recruitment_position_id=self.position,
                canonical_status=S.SUBMITTED,
                is_active=True,
            )


class PublicPortalTests(TestCase):
    def setUp(self):
        self.camp_service = CampaignService(tenant_id=TENANT, actor="test")
        self.campaign = self.camp_service.create_campaign(
            code="2026-PUB-001", title="公开招聘", campaign_type="SINGLE_POSITION"
        )
        self.position = self.camp_service.create_position(
            campaign_id=str(self.campaign.id),
            post_catalog_name="公开岗位",
            planned_headcount=1,
        )
        # 完整合法路径发布 + 开放
        self.camp_service.transition_campaign(str(self.campaign.id), target="UNDER_APPROVAL")
        self.camp_service.transition_campaign(str(self.campaign.id), target="APPROVED")
        self.camp_service.transition_campaign(str(self.campaign.id), target="PUBLISHED")
        self.camp_service.transition_campaign(str(self.campaign.id), target="OPEN")

    def test_public_campaign_by_token(self):
        url = reverse("hr04-public-campaign", kwargs={"token": self.campaign.public_token})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        # 服务端渲染标题（模板薄，岗位列表走 JS）
        self.assertContains(resp, "公开招聘")
        # JSON 端点返回岗位列表（JS 数据源）
        json_resp = self.client.get(url + "?format=json")
        payload = json.loads(json_resp.content)
        self.assertEqual(payload["data"]["campaign"]["title"], "公开招聘")
        self.assertEqual(len(payload["data"]["positions"]), 1)
        self.assertEqual(payload["data"]["positions"][0]["post_catalog_name"], "公开岗位")

    def test_public_campaign_invalid_token_404(self):
        url = reverse("hr04-public-campaign", kwargs={"token": "invalid-token"})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 404)

    def test_public_apply_creates_application(self):
        url = reverse("hr04-public-apply", kwargs={"token": self.campaign.public_token})
        resp = self.client.post(
            url,
            data=json.dumps(
                {
                    "position_id": str(self.position.id),
                    "legal_name": "候选人甲",
                    "primary_email": "cand-a@test.local",
                    "primary_mobile": "13800001111",
                }
            ),
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="pub-key-1",
        )
        self.assertEqual(resp.status_code, 201)
        payload = json.loads(resp.content)
        self.assertTrue(payload["data"]["application_no"])

    def test_public_apply_duplicate_idempotent(self):
        url = reverse("hr04-public-apply", kwargs={"token": self.campaign.public_token})
        body = json.dumps(
            {
                "position_id": str(self.position.id),
                "legal_name": "候选人乙",
                "primary_email": "cand-b@test.local",
            }
        )
        resp1 = self.client.post(
            url, data=body, content_type="application/json", HTTP_IDEMPOTENCY_KEY="pub-key-2"
        )
        resp2 = self.client.post(
            url, data=body, content_type="application/json", HTTP_IDEMPOTENCY_KEY="pub-key-2"
        )
        self.assertEqual(resp1.status_code, 201)
        self.assertEqual(resp2.status_code, 201)
        # 同 email+岗位只产生一条候选一条申请
        self.assertEqual(HrRecruitmentCandidate.objects.filter(primary_email="cand-b@test.local").count(), 1)
        self.assertEqual(
            HrJobApplication.objects.filter(
                tenant_id=TENANT,
                candidate_id__primary_email="cand-b@test.local",
                is_active=True,
            ).count(),
            1,
        )

    def test_public_my_applications_self_scope(self):
        """self scope：只返回本人申请，不泄漏他人。"""
        url = reverse("hr04-public-apply", kwargs={"token": self.campaign.public_token})
        self.client.post(
            url,
            data=json.dumps(
                {
                    "position_id": str(self.position.id),
                    "legal_name": "本人",
                    "primary_email": "me@test.local",
                }
            ),
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="me-key",
        )
        me_url = reverse("hr04-public-my-applications")
        resp = self.client.post(
            me_url,
            data=json.dumps({"primary_email": "me@test.local"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        payload = json.loads(resp.content)
        self.assertEqual(len(payload["data"]["applications"]), 1)

        resp_other = self.client.post(
            me_url,
            data=json.dumps({"primary_email": "other@test.local"}),
            content_type="application/json",
        )
        payload_other = json.loads(resp_other.content)
        self.assertEqual(payload_other["data"]["applications"], [])
