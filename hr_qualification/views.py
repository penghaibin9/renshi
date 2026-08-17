"""HR09 教师资格与双师型管理端页面。

页面只读取当前学校 Authority 模型，不消费仍待安全收口的旧 query-param tenant API。
"""

from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.shortcuts import render
from django.utils import timezone

from horilla.horilla_middlewares import get_selected_company
from hr_qualification.models import (
    HrDoubleTeacherApplication,
    HrDoubleTeacherRecognition,
    HrDoubleTeacherRecognitionBatch,
    HrPersonCredential,
    HrQualificationRiskCase,
)


SECTION_PERMISSIONS = {
    "overview": (
        "hr.qualification.credential.view",
        "hr.qualification.application.view",
        "hr.qualification.recognition.view",
        "hr.qualification.risk.view",
    ),
    "credentials": ("hr.qualification.credential.view",),
    "batches": ("hr.qualification.application.view", "hr.qualification.rule.view"),
    "applications": ("hr.qualification.application.view",),
    "recognitions": ("hr.qualification.recognition.view",),
    "risks": ("hr.qualification.risk.view",),
}

SECTION_TITLES = {
    "overview": "资格与双师工作台",
    "credentials": "资格证书台账",
    "batches": "双师认定批次",
    "applications": "双师申报审核",
    "recognitions": "双师认定结果",
    "risks": "资格风险中心",
}

CREDENTIAL_STATUS_ZH = {
    "DRAFT": "草稿",
    "SUBMITTED": "待核验",
    "UNDER_VERIFICATION": "核验中",
    "ACTIVE": "有效",
    "EXPIRED": "已过期",
    "SUSPENDED": "已暂停",
    "REVOKED": "已撤销",
    "INVALID": "无效",
    "SUPERSEDED": "已被新版本替代",
    "ARCHIVED": "已归档",
}

VERIFY_STATUS_ZH = {
    "": "尚未核验",
    "PENDING": "待核验",
    "IN_PROGRESS": "核验中",
    "VERIFIED": "已核验",
    "NOT_FOUND": "权威源未找到",
    "MISMATCH": "信息不一致",
    "EXPIRED": "核验发现过期",
    "REVOKED": "核验发现撤销",
    "NEEDS_MANUAL_REVIEW": "需人工复核",
    "PROVIDER_UNAVAILABLE": "核验来源暂不可用",
}

BATCH_STATUS_ZH = {
    "DRAFT": "草稿",
    "PUBLISHED": "已发布",
    "APPLICATION_OPEN": "申报中",
    "APPLICATION_CLOSED": "申报已截止",
    "REVIEWING": "评审中",
    "RESULT_PENDING": "待发布结果",
    "RESULT_PUBLISHED": "结果已发布",
    "CLOSED": "已结束",
}

APPLICATION_STATUS_ZH = {
    "DRAFT": "草稿",
    "PRECHECKING": "系统预检中",
    "READY": "可提交",
    "SUBMITTED": "已提交",
    "FORMAL_REVIEW": "形式审查中",
    "RETURNED": "退回补正",
    "RESUBMITTED": "已重新提交",
    "ELIGIBLE": "资格审查通过",
    "PANEL_REVIEW": "专家评审中",
    "RESULT_PENDING": "待审定结果",
    "RECOGNIZED": "认定通过",
    "NOT_RECOGNIZED": "未通过认定",
    "WITHDRAWN": "已撤回",
    "CANCELLED": "已取消",
    "OBJECTION": "异议处理中",
}

RECOGNITION_STATUS_ZH = {
    "PENDING_EFFECTIVE": "待生效",
    "ACTIVE": "有效",
    "REVIEW_DUE": "到期复核",
    "UNDER_REVIEW": "复核中",
    "EXPIRED": "已过期",
    "SUSPENDED": "已暂停",
    "REVOKED": "已撤销",
    "SUPERSEDED": "已升级替代",
    "INVALID": "无效",
}

LEVEL_ZH = {
    "DOUBLE_TEACHER_JUNIOR": "初级双师型",
    "DOUBLE_TEACHER_INTERMEDIATE": "中级双师型",
    "DOUBLE_TEACHER_SENIOR": "高级双师型",
}

RISK_TYPE_ZH = {
    "REQUIRED_CREDENTIAL_MISSING": "岗位必需资格缺失",
    "CREDENTIAL_UNVERIFIED": "资格尚未核验",
    "CREDENTIAL_EXPIRING": "资格即将到期",
    "CREDENTIAL_EXPIRED": "资格已过期",
    "CREDENTIAL_REVOKED": "资格已被撤销",
    "CERTIFICATE_DOCUMENT_MISSING": "证书材料缺失",
    "VERIFICATION_PROVIDER_ERROR": "核验来源异常",
    "DOUBLE_TEACHER_EVIDENCE_INVALIDATED": "双师认定证据失效",
}

RISK_STATUS_ZH = {
    "OPEN": "待处理",
    "ACKNOWLEDGED": "已确认",
    "IN_PROGRESS": "处理中",
    "RESOLVED": "已解决",
    "DISMISSED": "已排除",
    "CLOSED": "已关闭",
}

RISK_SEVERITY_ZH = {
    "CRITICAL": "严重",
    "HIGH": "高",
    "MEDIUM": "中",
    "LOW": "低",
}


def _resolve_tenant_id():
    selected = get_selected_company()
    if selected in (None, "", "all"):
        return None
    try:
        return int(selected)
    except (TypeError, ValueError):
        return None


def _require_section_permission(user, section):
    if user.is_superuser:
        return
    allowed = SECTION_PERMISSIONS.get(section, SECTION_PERMISSIONS["overview"])
    if not any(user.has_perm(code) for code in allowed):
        raise PermissionDenied("没有教师资格与双师型管理访问权限")


def _person_label(staff_master=None, person=None):
    person_obj = person or getattr(staff_master, "person_id", None)
    name = getattr(person_obj, "legal_name", "") or "未命名人员"
    staff_no = getattr(staff_master, "staff_no", "")
    return f"{name} · {staff_no}" if staff_no else name


@login_required
def qualification_workspace(request, section="overview"):
    if section not in SECTION_TITLES:
        section = "overview"
    _require_section_permission(request.user, section)

    tenant_id = _resolve_tenant_id()
    if tenant_id is None:
        return render(
            request,
            "hr_qualification/workspace.html",
            {
                "section": section,
                "section_title": SECTION_TITLES[section],
                "access_error": "请选择当前学校后再进入资格与双师型管理。",
            },
            status=403,
        )

    today = timezone.localdate()
    next_90 = today + timedelta(days=90)

    credentials = HrPersonCredential.objects.filter(tenant_id=tenant_id)
    batches = HrDoubleTeacherRecognitionBatch.objects.filter(tenant_id=tenant_id)
    applications = HrDoubleTeacherApplication.objects.filter(tenant_id=tenant_id)
    recognitions = HrDoubleTeacherRecognition.objects.filter(tenant_id=tenant_id)
    risks = HrQualificationRiskCase.objects.filter(tenant_id=tenant_id)

    open_risk_statuses = ["OPEN", "ACKNOWLEDGED", "IN_PROGRESS"]
    pending_application_statuses = [
        "SUBMITTED",
        "FORMAL_REVIEW",
        "RETURNED",
        "RESUBMITTED",
        "ELIGIBLE",
        "PANEL_REVIEW",
        "RESULT_PENDING",
        "OBJECTION",
    ]
    active_batch_statuses = [
        "PUBLISHED",
        "APPLICATION_OPEN",
        "APPLICATION_CLOSED",
        "REVIEWING",
        "RESULT_PENDING",
    ]

    summary = {
        "active_credentials": credentials.filter(status="ACTIVE").count(),
        "pending_verification": credentials.filter(
            Q(status__in=["SUBMITTED", "UNDER_VERIFICATION"])
            | Q(current_verification_status__in=["PENDING", "IN_PROGRESS", "NEEDS_MANUAL_REVIEW"])
        ).count(),
        "expiring_90": credentials.filter(
            status="ACTIVE", valid_to__gte=today, valid_to__lte=next_90
        ).count(),
        "open_risks": risks.filter(status__in=open_risk_statuses).count(),
        "active_batches": batches.filter(status__in=active_batch_statuses).count(),
        "pending_applications": applications.filter(status__in=pending_application_statuses).count(),
        "active_recognitions": recognitions.filter(status="ACTIVE").count(),
        "review_due_90": recognitions.filter(
            status__in=["ACTIVE", "REVIEW_DUE", "UNDER_REVIEW"],
            review_due_at__isnull=False,
            review_due_at__lte=next_90,
        ).count(),
    }

    focus_items = []
    if summary["open_risks"]:
        focus_items.append({
            "level": "danger",
            "title": f"{summary['open_risks']} 条资格风险待处理",
            "desc": "优先处理证书失效、核验异常和双师证据失效，避免影响任职或认定结果。",
            "url": "/hr/qualifications/risks/",
            "action": "进入风险中心",
        })
    if summary["pending_verification"]:
        focus_items.append({
            "level": "warning",
            "title": f"{summary['pending_verification']} 份资格待核验",
            "desc": "先核验证书真实性和有效期，再用于岗位资格、双师认定或其它业务判断。",
            "url": "/hr/qualifications/credentials/",
            "action": "处理资格核验",
        })
    if summary["pending_applications"]:
        focus_items.append({
            "level": "info",
            "title": f"{summary['pending_applications']} 份双师申报在办理中",
            "desc": "按形式审查、专家评审、审定结果逐级处理，不跳过证据和利益冲突检查。",
            "url": "/hr/double-teacher/applications/",
            "action": "进入申报审核",
        })
    if summary["review_due_90"]:
        focus_items.append({
            "level": "warning",
            "title": f"{summary['review_due_90']} 条双师认定 90 天内需复核",
            "desc": "复核前先检查依赖资格、企业实践和其它证据是否仍然有效。",
            "url": "/hr/double-teacher/recognitions/",
            "action": "查看待复核结果",
        })

    credential_rows = []
    for item in credentials.select_related(
        "catalog_item_id", "staff_master_id__person_id"
    ).order_by("valid_to", "-updated_at")[:30]:
        credential_rows.append({
            "person": _person_label(item.staff_master_id, item.person_id),
            "name": item.credential_name_snapshot,
            "issuer": item.issuer_name or "—",
            "valid_to": item.valid_to,
            "status": CREDENTIAL_STATUS_ZH.get(item.status, item.status),
            "verify": VERIFY_STATUS_ZH.get(
                item.current_verification_status, item.current_verification_status or "尚未核验"
            ),
            "masked_no": item.masked_no,
            "is_expiring": bool(
                item.status == "ACTIVE"
                and item.valid_to
                and today <= item.valid_to <= next_90
            ),
        })

    batch_rows = []
    for item in batches.order_by("-application_start", "-created_at")[:20]:
        batch_rows.append({
            "no": item.batch_no,
            "name": item.name,
            "year": item.school_year or "—",
            "start": item.application_start,
            "end": item.application_end,
            "status": BATCH_STATUS_ZH.get(item.status, item.status),
            "target_levels": [LEVEL_ZH.get(x, x) for x in (item.target_levels or [])],
        })

    application_rows = []
    for item in applications.select_related(
        "batch_id", "staff_master_id__person_id"
    ).order_by("-submitted_at", "-updated_at")[:30]:
        application_rows.append({
            "no": item.application_no,
            "person": _person_label(item.staff_master_id, item.person_id),
            "batch": item.batch_id.name,
            "level": LEVEL_ZH.get(item.target_level, item.target_level),
            "route": "特殊通道" if item.route == "EXCEPTION" else "常规申报",
            "status": APPLICATION_STATUS_ZH.get(item.status, item.status),
            "submitted_at": item.submitted_at,
        })

    recognition_rows = []
    for item in recognitions.select_related(
        "staff_master_id__person_id", "batch_id"
    ).order_by("review_due_at", "-effective_from")[:30]:
        recognition_rows.append({
            "no": item.recognition_no,
            "person": _person_label(item.staff_master_id, item.person_id),
            "level": LEVEL_ZH.get(item.level, item.level),
            "status": RECOGNITION_STATUS_ZH.get(item.status, item.status),
            "effective_from": item.effective_from,
            "effective_to": item.effective_to,
            "review_due_at": item.review_due_at,
            "authority": item.recognition_authority or "—",
            "review_due_soon": bool(
                item.review_due_at and item.review_due_at <= next_90
            ),
        })

    risk_rows = []
    for item in risks.select_related("person_id").order_by("due_at", "-opened_at")[:30]:
        risk_rows.append({
            "person": _person_label(person=item.person_id),
            "risk": RISK_TYPE_ZH.get(item.risk_type, item.risk_type),
            "severity": RISK_SEVERITY_ZH.get(item.severity, item.severity),
            "status": RISK_STATUS_ZH.get(item.status, item.status),
            "owner": item.owner or "待分派",
            "due_at": item.due_at,
            "opened_at": item.opened_at,
        })

    return render(
        request,
        "hr_qualification/workspace.html",
        {
            "tenant_id": tenant_id,
            "today": today,
            "section": section,
            "section_title": SECTION_TITLES[section],
            "summary": summary,
            "focus_items": focus_items,
            "credential_rows": credential_rows,
            "batch_rows": batch_rows,
            "application_rows": application_rows,
            "recognition_rows": recognition_rows,
            "risk_rows": risk_rows,
        },
    )
