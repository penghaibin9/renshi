"""
hr_recruitment/labels.py

JSON 字段规范（总控 §12）：机器字段名 camelCase 不改，人看的中文用成对字段：
  {status: "ACTIVE", statusLabel: "在职"}
  {genderCode: "F", genderLabel: "女"}

数据库枚举值不改，只在此映射到展示 label（不落库、不影响状态机/迁移）。
"""

from django.utils.translation import gettext_lazy as _

from hr_recruitment import constants

# 状态枚举值 → 中文 label（纯展示层映射）
APPLICATION_STATUS_LABELS = {
    constants.ApplicationCanonicalStatus.DRAFT: _("草稿"),
    constants.ApplicationCanonicalStatus.SUBMITTED: _("已提交"),
    constants.ApplicationCanonicalStatus.UNDER_REVIEW: _("审核中"),
    constants.ApplicationCanonicalStatus.RETURNED: _("已退回补件"),
    constants.ApplicationCanonicalStatus.RESUBMITTED: _("已重新提交"),
    constants.ApplicationCanonicalStatus.QUALIFIED: _("资格通过"),
    constants.ApplicationCanonicalStatus.DISQUALIFIED: _("资格不符"),
    constants.ApplicationCanonicalStatus.ASSESSMENT_PENDING: _("待选拔"),
    constants.ApplicationCanonicalStatus.ASSESSING: _("选拔中"),
    constants.ApplicationCanonicalStatus.ASSESSMENT_PASSED: _("选拔通过"),
    constants.ApplicationCanonicalStatus.ASSESSMENT_FAILED: _("选拔未通过"),
    constants.ApplicationCanonicalStatus.MEDICAL_PENDING: _("待体检"),
    constants.ApplicationCanonicalStatus.MEDICAL_REVIEW: _("体检中"),
    constants.ApplicationCanonicalStatus.BACKGROUND_PENDING: _("待考察"),
    constants.ApplicationCanonicalStatus.BACKGROUND_REVIEW: _("考察中"),
    constants.ApplicationCanonicalStatus.PROPOSED_HIRE: _("拟录用"),
    constants.ApplicationCanonicalStatus.PUBLIC_NOTICE: _("公示中"),
    constants.ApplicationCanonicalStatus.OFFER_PENDING: _("待发 Offer"),
    constants.ApplicationCanonicalStatus.OFFERED: _("已发 Offer"),
    constants.ApplicationCanonicalStatus.OFFER_ACCEPTED: _("Offer 已接受"),
    constants.ApplicationCanonicalStatus.OFFER_DECLINED: _("Offer 已婉拒"),
    constants.ApplicationCanonicalStatus.HANDOFF_TO_HR05: _("已交接 HR05"),
    constants.ApplicationCanonicalStatus.WITHDRAWN: _("已撤回"),
    constants.ApplicationCanonicalStatus.CANCELLED: _("已取消"),
}

CAMPAIGN_STATUS_LABELS = {
    constants.CampaignStatus.DRAFT: _("草稿"),
    constants.CampaignStatus.UNDER_APPROVAL: _("审批中"),
    constants.CampaignStatus.APPROVED: _("已批准"),
    constants.CampaignStatus.PUBLISHED: _("已发布"),
    constants.CampaignStatus.OPEN: _("报名中"),
    constants.CampaignStatus.CLOSED: _("已关闭"),
    constants.CampaignStatus.RESULT_PROCESSING: _("结果处理中"),
    constants.CampaignStatus.COMPLETED: _("已完成"),
    constants.CampaignStatus.ARCHIVED: _("已归档"),
}

POSITION_STATUS_LABELS = {
    constants.RecruitmentPositionStatus.DRAFT: _("草稿"),
    constants.RecruitmentPositionStatus.READY: _("就绪"),
    constants.RecruitmentPositionStatus.OPEN: _("报名中"),
    constants.RecruitmentPositionStatus.CLOSED: _("已关闭"),
    constants.RecruitmentPositionStatus.SELECTION: _("选拔中"),
    constants.RecruitmentPositionStatus.PROPOSED_HIRE: _("拟录用"),
    constants.RecruitmentPositionStatus.FILLED: _("已录满"),
    constants.RecruitmentPositionStatus.PARTIALLY_FILLED: _("部分录满"),
    constants.RecruitmentPositionStatus.CANCELLED: _("已取消"),
}

PLAN_REQUEST_STATUS_LABELS = {
    constants.PlanRequestStatus.DRAFT: _("草稿"),
    constants.PlanRequestStatus.SUBMITTED: _("已提交"),
    constants.PlanRequestStatus.UNDER_HR_REVIEW: _("人事审核中"),
    constants.PlanRequestStatus.RETURNED: _("已退回"),
    constants.PlanRequestStatus.RESUBMITTED: _("已重新提交"),
    constants.PlanRequestStatus.UNDER_SCHOOL_APPROVAL: _("学校审批中"),
    constants.PlanRequestStatus.APPROVED: _("已批准"),
    constants.PlanRequestStatus.PARTIALLY_APPROVED: _("部分批准"),
    constants.PlanRequestStatus.REJECTED: _("已驳回"),
    constants.PlanRequestStatus.CLOSED: _("已关闭"),
}

CANDIDATE_STATUS_LABELS = {
    constants.CandidateStatus.ACTIVE: _("正常"),
    constants.CandidateStatus.ANONYMIZED: _("已匿名化"),
    constants.CandidateStatus.BLOCKED: _("已冻结"),
}

OFFER_STATUS_LABELS = {
    constants.OfferStatus.DRAFT: _("草稿"),
    constants.OfferStatus.APPROVED: _("已批准"),
    constants.OfferStatus.ISSUED: _("已签发"),
    constants.OfferStatus.VIEWED: _("已查看"),
    constants.OfferStatus.ACCEPTED: _("已接受"),
    constants.OfferStatus.DECLINED: _("已婉拒"),
    constants.OfferStatus.EXPIRED: _("已过期"),
    constants.OfferStatus.WITHDRAWN: _("已撤回"),
}

PROPOSED_HIRE_STATUS_LABELS = {
    constants.ProposedHireDecision.PROPOSE: _("待审批"),
    constants.ProposedHireDecision.APPROVE: _("已批准"),
    constants.ProposedHireDecision.REJECT: _("已驳回"),
    constants.ProposedHireDecision.WITHDRAW: _("已撤回"),
}

NOTICE_STATUS_LABELS = {
    constants.PublicNoticeStatus.DRAFT: _("草稿"),
    constants.PublicNoticeStatus.PUBLISHED: _("已发布"),
    constants.PublicNoticeStatus.ACTIVE: _("公示中"),
    constants.PublicNoticeStatus.CLOSED_NO_BLOCKER: _("已结束无异议"),
    constants.PublicNoticeStatus.CLOSED_WITH_OBJECTION: _("已结束有异议"),
    constants.PublicNoticeStatus.CANCELLED: _("已取消"),
}

SCORE_SHEET_STATUS_LABELS = {
    constants.ScoreSheetStatus.DRAFT: _("草稿"),
    constants.ScoreSheetStatus.SUBMITTED: _("已提交"),
    constants.ScoreSheetStatus.LOCKED: _("已锁定"),
    constants.ScoreSheetStatus.VOID: _("作废"),
    constants.ScoreSheetStatus.REOPEN_REQUESTED: _("待解锁"),
    constants.ScoreSheetStatus.REOPEN_APPROVED: _("已批准解锁"),
}

NEED_TYPE_LABELS = {
    constants.NeedType.NEW: _("新增"),
    constants.NeedType.REPLACEMENT: _("补充"),
    constants.NeedType.TALENT: _("人才引进"),
    constants.NeedType.TEMPORARY: _("临时"),
}


def status_label(mapping: dict, value: str | None) -> str:
    """取状态的中文 label（无映射时回退为原值，不改机器字段）。"""
    if value is None:
        return ""
    return str(mapping.get(value, value))
