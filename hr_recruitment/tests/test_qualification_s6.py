"""
hr_recruitment/tests/test_qualification_s6.py

HR04-04 资格审查（S6）测试：
- 系统预检只建议不终审（PASS/FAIL/DATA_MISSING/NEEDS_MANUAL_REVIEW）；
- 规则集版本 LOCKED 后不可变（旧申请不被新条件重写）；
- RETURNED = 材料缺失可补正（必填缺项/原因），≠ DISQUALIFIED；
- DISQUALIFIED 必须记录原因；最终结论记录审核人；
- 决策写 ledger。
"""

from datetime import date
from uuid import uuid4

from django.test import TestCase

from hr_recruitment.constants import ApplicationCanonicalStatus as S
from hr_recruitment.models import (
    HrApplicationTransition,
    HrJobApplication,
    HrQualificationDecision,
    HrQualificationRuleSetVersion,
)
from hr_recruitment.services.application_service import ApplicationService
from hr_recruitment.services.campaign_service import CampaignService
from hr_recruitment.services.candidate_service import CandidateService
from hr_recruitment.services.qualification_service import QualificationService

TENANT = 5001


class QualificationServiceTests(TestCase):
    def setUp(self):
        self.camp_service = CampaignService(tenant_id=TENANT, actor="test")
        self.campaign = self.camp_service.create_campaign(
            code="2026-Q-001", title="资格测试", campaign_type="SINGLE_POSITION"
        )
        self.position = self.camp_service.create_position(
            campaign_id=str(self.campaign.id),
            post_catalog_name="软件工程专任教师",
            planned_headcount=1,
        )
        self.candidate_service = CandidateService(tenant_id=TENANT)
        self.candidate = self.candidate_service.create_candidate(
            legal_name="张三", primary_email="qual@test.local"
        )
        self.app_service = ApplicationService(tenant_id=TENANT, actor="test")
        draft = self.app_service.save_draft(
            candidate_id=str(self.candidate.id),
            recruitment_position_id=str(self.position.id),
            form_data={"degree": "博士", "major": "计算机", "work_years": 3},
        )
        self.app = self.app_service.submit(application_id=str(draft.id))
        self.qual_service = QualificationService(tenant_id=TENANT, actor="reviewer-1")

    def _make_locked_rule_set(self):
        rs = self.qual_service.create_rule_set(position_id=str(self.position.id))
        self.qual_service.add_rule(
            rule_set_version_id=str(rs.id),
            rule_code="DEGREE",
            label="学历要求博士",
            operator="eq",
            expected_value={"field": "degree", "value": "博士"},
            severity="HARD",
        )
        self.qual_service.add_rule(
            rule_set_version_id=str(rs.id),
            rule_code="WORK_YEARS",
            label="工作年限≥3",
            operator="gte",
            expected_value={"field": "work_years", "value": 3},
            severity="SOFT",
        )
        self.qual_service.lock_rule_set(rule_set_version_id=str(rs.id))
        return rs

    def test_precheck_advisory_only(self):
        rs = self._make_locked_rule_set()
        # 绑定规则集到申请
        self.app.qualification_rule_version_id = rs.id
        self.app.save(update_fields=["qualification_rule_version_id"])
        result = self.qual_service.run_precheck(application_id=str(self.app.id))
        self.assertTrue(result["advisory_only"])
        self.assertEqual(result["overall_suggestion"], "PASS")
        self.assertEqual(len(result["results"]), 2)

    def test_precheck_data_missing(self):
        rs = self._make_locked_rule_set()
        self.app.form_snapshot = {"degree": "博士"}
        self.app.qualification_rule_version_id = rs.id
        self.app.save(update_fields=["form_snapshot", "qualification_rule_version_id"])
        result = self.qual_service.run_precheck(application_id=str(self.app.id))
        self.assertEqual(result["overall_suggestion"], "DATA_MISSING")

    def test_start_review_and_qualified(self):
        self.qual_service.start_review(application_id=str(self.app.id))
        self.app.refresh_from_db()
        self.assertEqual(self.app.canonical_status, S.UNDER_REVIEW)
        self.qual_service.decision(
            application_id=str(self.app.id),
            decision="QUALIFIED",
            reason_text="条件全部满足",
        )
        self.app.refresh_from_db()
        self.assertEqual(self.app.canonical_status, S.QUALIFIED)
        decision = HrQualificationDecision.objects.filter(
            application_id=self.app, decision="QUALIFIED"
        ).first()
        self.assertIsNotNone(decision)
        self.assertEqual(decision.decided_by, "reviewer-1")

    def test_returned_requires_reason(self):
        self.qual_service.start_review(application_id=str(self.app.id))
        from hr_recruitment.services.qualification_service import QualificationServiceError

        with self.assertRaises(QualificationServiceError):
            self.qual_service.decision(
                application_id=str(self.app.id),
                decision="RETURNED",
            )
        self.qual_service.decision(
            application_id=str(self.app.id),
            decision="RETURNED",
            reason_text="学历材料不完整",
            missing_items=["学位证书"],
        )
        self.app.refresh_from_db()
        self.assertEqual(self.app.canonical_status, S.RETURNED)

    def test_disqualified_requires_reason(self):
        self.qual_service.start_review(application_id=str(self.app.id))
        from hr_recruitment.services.qualification_service import QualificationServiceError

        with self.assertRaises(QualificationServiceError):
            self.qual_service.decision(
                application_id=str(self.app.id),
                decision="DISQUALIFIED",
            )
        self.qual_service.decision(
            application_id=str(self.app.id),
            decision="DISQUALIFIED",
            reason_text="学历不满足博士要求",
        )
        self.app.refresh_from_db()
        self.assertEqual(self.app.canonical_status, S.DISQUALIFIED)

    def test_decision_writes_ledger(self):
        self.qual_service.start_review(application_id=str(self.app.id))
        self.qual_service.decision(
            application_id=str(self.app.id), decision="QUALIFIED", reason_text="ok"
        )
        ledger = HrApplicationTransition.objects.filter(
            application_id=self.app, action="QUALIFICATION_QUALIFIED"
        )
        self.assertEqual(ledger.count(), 1)

    def test_rule_set_locked_immutable(self):
        rs = self._make_locked_rule_set()
        from hr_recruitment.services.qualification_service import QualificationServiceError

        with self.assertRaises(QualificationServiceError):
            self.qual_service.add_rule(
                rule_set_version_id=str(rs.id),
                rule_code="NEW_RULE",
                label="锁定后不可添加",
            )
        rs.refresh_from_db()
        self.assertEqual(rs.status, "ACTIVE")
