"""
hr_recruitment/selectors/pipeline.py

Pipeline/Kanban 从 HR04 权威数据投影（§36 验收：Pipeline 可正常显示）。

- 列 = workflow_stage 分组（展示阶段，非权威状态）；
- 卡片显示候选人摘要（服务端裁剪 PII）；
- 数据源为 HrJobApplication.canonical_status + workflow_stage_name（权威），
  不读 legacy stage_type（§29 authority 分层）。
"""

from __future__ import annotations

from hr_recruitment.constants import ApplicationCanonicalStatus as S
from hr_recruitment.labels import APPLICATION_STATUS_LABELS, status_label
from hr_recruitment.models import HrJobApplication


def pipeline_boards(*, tenant_id, campaign_id=None, position_id=None, scope=None):
    """按 workflow_stage 分组生成看板列（含候选卡片）。"""
    qs = HrJobApplication.objects.filter(tenant_id=tenant_id, is_active=True).select_related(
        "candidate_id", "recruitment_position_id"
    )
    if position_id:
        qs = qs.filter(recruitment_position_id_id=position_id)
    elif campaign_id:
        qs = qs.filter(recruitment_position_id__campaign_id_id=campaign_id)
    if scope:
        from hr_recruitment.selectors.scope_utils import apply_org_scope

        qs = apply_org_scope(
            qs, scope, org_field="recruitment_position_id__organization_id"
        )

    # 按展示阶段分组（优先 workflow_stage_name，缺省按 canonical_status 映射）
    columns: dict[str, list] = {}
    for app in qs.order_by("submitted_at"):
        stage = app.workflow_stage_name or _default_stage(app.canonical_status)
        columns.setdefault(stage, []).append(
            {
                "application_id": str(app.id),
                "application_no": app.application_no,
                "candidate_uid": app.candidate_id.candidate_uid if app.candidate_id else "",
                "candidate_name": app.candidate_id.legal_name if app.candidate_id else "",
                "position": app.recruitment_position_id.post_catalog_name
                if app.recruitment_position_id
                else "",
                "canonical_status": app.canonical_status,
                "statusLabel": status_label(APPLICATION_STATUS_LABELS, app.canonical_status),
                "submitted_at": app.submitted_at.isoformat() if app.submitted_at else None,
            }
        )

    return [
        {
            "stage": stage,
            "count": len(cards),
            "cards": cards,
        }
        for stage, cards in columns.items()
    ]


def _default_stage(canonical_status: str) -> str:
    """canonical_status → 默认展示阶段（仅展示，非权威）。"""
    mapping = {
        S.DRAFT: "草稿",
        S.SUBMITTED: "已提交",
        S.UNDER_REVIEW: "资格审查",
        S.RETURNED: "退回补件",
        S.RESUBMITTED: "资格审查",
        S.QUALIFIED: "已过资格",
        S.ASSESSMENT_PENDING: "待选拔",
        S.ASSESSING: "选拔中",
        S.ASSESSMENT_PASSED: "选拔通过",
        S.ASSESSMENT_FAILED: "未通过",
        S.MEDICAL_PENDING: "待体检",
        S.MEDICAL_REVIEW: "体检中",
        S.BACKGROUND_PENDING: "待考察",
        S.BACKGROUND_REVIEW: "考察中",
        S.PROPOSED_HIRE: "拟录用",
        S.PUBLIC_NOTICE: "公示中",
        S.OFFER_PENDING: "待发 Offer",
        S.OFFERED: "已发 Offer",
        S.OFFER_ACCEPTED: "Offer 已接受",
        S.OFFER_DECLINED: "Offer 已婉拒",
        S.HANDOFF_TO_HR05: "已交接 HR05",
        S.WITHDRAWN: "已撤回",
        S.CANCELLED: "已取消",
    }
    return mapping.get(canonical_status, canonical_status)
