"""
hr_external/api/views.py —— HR08 API 视图（S1 骨架 + S3 外聘教师库）。

已挂：
- GET  /api/hr/v1/external-teachers/categories        类别目录
- GET  /api/hr/v1/external-teachers/contract          契约探针
- GET  /api/hr/v1/external-teachers                   profile 列表（S3）
- POST /api/hr/v1/external-teachers                   profile 创建（S3）
- POST /api/hr/v1/external-teachers/identity-match    身份匹配（S3）
- GET  /api/hr/v1/external-teachers/{id}              profile 详情（S3）
- GET  /api/hr/v1/external-teachers/{id}/engagements  受聘历史（S3）
- GET  /api/hr/v1/external-teachers/{id}/history      履历时间线（S3）

后续阶段：S5 hiring-cases / S7 tasks / workload / S8 renewals / exits。
"""

from __future__ import annotations

import json

from django.http import JsonResponse
from django.utils.dateparse import parse_date

from hr_external.api.base import (
    api_root,
    error_response,
    json_response,
    make_external_context,
)
from hr_external.constants import ExternalWorkerCategory, HR08_PERMISSIONS
from hr_external.display_labels import (
    _label,
    agreement_status_label,
    category_label,
    engagement_status_label,
    ethics_status_label,
    identity_verification_label,
    pool_status_label,
)
from hr_external.models import (
    HrExternalEngagement,
    HrExternalImportJob,
    HrExternalLifecycleEvent,
    HrExternalTeacherProfile,
)
from hr_external.permissions import require_hr_external_permission
from hr_external.selectors import list_external_profiles
from hr_external.selectors.profile_selector import ProfileFilterSpec
from hr_external.services.audit_service import write_external_audit
from hr_external.services.category_service import CategoryService
from hr_external.services.identity_match_service import IdentityMatchService
from hr_external.services.import_service import (
    ImportCommitError,
    ImportService,
    ImportValidationError,
)
from hr_external.services.profile_service import ProfileService


def contract_probe(request):
    """契约探针：验证 envelope 结构。"""
    body = api_root(request)
    body["data"] = {
        "resource": "external-teachers",
        "schema": "hr08.base.1",
        "permissions": list(HR08_PERMISSIONS),
        "categories": [c for c, _ in ExternalWorkerCategory.choices],
    }
    return json_response(request, body)


@require_hr_external_permission("hr08.profile.view")
def category_catalog(request):
    """
    GET /api/hr/v1/external-teachers/categories
    返回当前 tenant 的外聘类别目录（含默认集注入）。
    """
    try:
        ctx = make_external_context(request, authority_mode="LEGACY_EMPLOYEE_TAG_ONLY")
    except Exception as exc:  # noqa: BLE001 —— 统一信封
        code = getattr(exc, "code", "INVALID_REQUEST")
        return error_response(request, code, str(exc), 403 if code == "TENANT_CONTEXT_REQUIRED" else 400)

    service = CategoryService()
    service.ensure_default_categories(ctx.tenant_id)

    items = []
    for cat in service.list_categories(ctx.tenant_id):
        items.append(
            {
                "id": str(cat.id),
                "code": cat.code,
                "name": cat.name,
                "nameLabel": cat.name,  # 已中文（name 即类别中文名）
                "isSystemBuiltin": cat.is_system_builtin,
                "requiresOpenSelection": cat.requires_open_selection,
                "requiresEthicsReview": cat.requires_ethics_review,
                "requiresTeacherQualification": cat.requires_teacher_qualification,
                "requiresIndustryExperience": cat.requires_industry_experience,
                "defaultEngagementMonths": cat.default_engagement_months,
                "allowMultipleAssignments": cat.allow_multiple_assignments,
                "allowTeaching": cat.allow_teaching,
                "allowResearch": cat.allow_research,
                "agreementRequirement": cat.agreement_requirement,
                "agreementRequirementLabel": _agreement_requirement_label(cat.agreement_requirement),
                "version": cat.version,
            }
        )

    body = api_root(request)
    body["data"] = {"items": items, "total": len(items)}
    return json_response(request, body)


def _ctx(request):
    """构造上下文；失败返回 (None, error_response)。"""
    try:
        return make_external_context(request, authority_mode="LEGACY_EMPLOYEE_TAG_ONLY"), None
    except Exception as exc:  # noqa: BLE001
        code = getattr(exc, "code", "INVALID_REQUEST")
        status = 403 if code == "TENANT_CONTEXT_REQUIRED" else 400
        return None, error_response(request, code, str(exc), status)


def _agreement_requirement_label(value: str) -> str:
    return {
        "NOT_REQUIRED": "无需协议",
        "REQUIRED_BEFORE_ACTIVATION": "激活前必须签署协议",
        "REQUIRED_AFTER_ACTIVATION_GRACE": "激活后宽限期内签署",
    }.get(value, value)


@require_hr_external_permission("hr08.profile.view")
def profile_collection(request):
    """
    GET  /api/hr/v1/external-teachers   列表（S3）
    POST /api/hr/v1/external-teachers   创建（S3）
    """
    if request.method == "POST":
        return _profile_create(request)
    return _profile_list(request)


@require_hr_external_permission("hr08.profile.view")
def _profile_list(request):
    """
    GET /api/hr/v1/external-teachers?keyword=&category=&source_organization=
        &industry_domain=&professional_title=&skill_level=&pool_status=
        &currently_engaged=&scope_type=&page=&page_size=
    """
    ctx, err = _ctx(request)
    if err:
        return err

    def _bool(v):
        if v in (None, ""):
            return None
        return v.lower() in ("1", "true", "yes", "on")

    def _int(v, default):
        try:
            return int(v)
        except (TypeError, ValueError):
            return default

    spec = ProfileFilterSpec(
        tenant_id=ctx.tenant_id,
        keyword=request.GET.get("keyword", ""),
        category_code=request.GET.get("category", ""),
        source_organization=request.GET.get("source_organization", ""),
        industry_domain=request.GET.get("industry_domain", ""),
        professional_title=request.GET.get("professional_title", ""),
        skill_level=request.GET.get("skill_level", ""),
        has_teacher_qualification=_bool(request.GET.get("has_teacher_qualification")),
        pool_status=request.GET.get("pool_status", ""),
        currently_engaged=_bool(request.GET.get("currently_engaged")),
        host_organization_id=_int(request.GET.get("host_organization_id"), None),
        page=_int(request.GET.get("page"), 1),
        page_size=_int(request.GET.get("page_size"), 50),
        order_by=request.GET.get("order_by", "-updated_at"),
    )
    total, items = list_external_profiles(spec, ctx=ctx)
    body = api_root(request)
    body["data"] = {
        "items": items,
        "total": total,
        "page": spec.page,
        "pageSize": spec.page_size,
    }
    return json_response(request, body)


@require_hr_external_permission("hr08.profile.create")
def _profile_create(request):
    """
    POST /api/hr/v1/external-teachers
    body: {
      legalName, preferredName?, genderCode?, birthDate?, nationalityCode?,
      documentNumber?, documentType?, sourceOrganizationName?, sourceOrganizationType?,
      sourcePositionTitle?, industryDomain?, expertiseTags?[],
      highestProfessionalTitle?, highestSkillLevel?, primaryCategoryCode?, poolStatus?
    }
    身份根：复用 HR03 PersonIdentityService（HARD 幂等；LIKELY 人工去重）。
    """
    ctx, err = _ctx(request)
    if err:
        return err

    try:
        payload = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return error_response(request, "INVALID_REQUEST", "请求体必须是 JSON", 400)

    legal_name = (payload.get("legalName") or "").strip()
    if not legal_name:
        return error_response(request, "INVALID_REQUEST", "legalName 必填", 400)

    from hr_external.integrations.hr03 import PersonProvider

    person_result = PersonProvider().create_person(
        tenant_id=ctx.tenant_id,
        legal_name=legal_name,
        preferred_name=payload.get("preferredName") or "",
        gender_code=payload.get("genderCode"),
        birth_date=parse_date(payload["birthDate"]) if payload.get("birthDate") else None,
        nationality_code=payload.get("nationalityCode") or "",
        document_number=payload.get("documentNumber") or None,
        document_type=payload.get("documentType") or "NATIONAL_ID",
    )
    if not person_result.is_available:
        # 疑似重复 → 409（人工去重），不 500（A28）
        status = 409 if person_result.error_code == "PERSON_DUPLICATE_REVIEW_REQUIRED" else 400
        return error_response(request, person_result.error_code, person_result.error_message, status)

    person_id = person_result.data["personId"]
    service = ProfileService()
    try:
        profile = service.create_profile(
            tenant_id=ctx.tenant_id,
            person_id=person_id,
            primary_category_code=payload.get("primaryCategoryCode"),
            source_organization_name=payload.get("sourceOrganizationName") or "",
            source_organization_type=payload.get("sourceOrganizationType") or "",
            source_position_title=payload.get("sourcePositionTitle") or "",
            industry_domain=payload.get("industryDomain") or "",
            expertise_tags=payload.get("expertiseTags") or [],
            highest_professional_title=payload.get("highestProfessionalTitle") or "",
            highest_skill_level=payload.get("highestSkillLevel") or "",
            candidate_pool_status=payload.get("poolStatus") or "AVAILABLE",
        )
    except Exception as exc:  # noqa: BLE001 —— 统一信封
        code = getattr(exc, "code", "INVALID_REQUEST")
        return error_response(request, code, str(exc), 409 if code == "EXTERNAL_DUPLICATE_PROFILE" else 400)

    write_external_audit(
        tenant_id=ctx.tenant_id,
        action="ExternalProfileCreated",
        actor_user_id=ctx.user_id,
        external_profile_id=profile.id,
        business_type="HR08_PROFILE",
        business_id=str(profile.id),
        source="api",
        request_id=request.GET.get("requestId", ""),
    )

    body = api_root(request)
    body["data"] = {
        "id": str(profile.id),
        "externalTeacherNo": profile.external_teacher_no,
        "personId": str(profile.person_id_id),
    }
    return json_response(request, body, status=201)


@require_hr_external_permission("hr08.profile.view")
def identity_match(request):
    """
    POST /api/hr/v1/external-teachers/identity-match
    body: { documentNumber?, legalName?, birthDate?, phone?, email?, sourceOrganization? }
    身份证只 exact match 且受控（§24.3）；响应不返回明文证件号。
    """
    ctx, err = _ctx(request)
    if err:
        return err

    try:
        payload = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return error_response(request, "INVALID_REQUEST", "请求体必须是 JSON", 400)

    result = IdentityMatchService().match(
        tenant_id=ctx.tenant_id,
        document_number=payload.get("documentNumber") or None,
        legal_name=payload.get("legalName") or "",
        birth_date=parse_date(payload["birthDate"]) if payload.get("birthDate") else None,
        phone=payload.get("phone") or "",
        email=payload.get("email") or "",
        source_organization=payload.get("sourceOrganization") or "",
    )

    body = api_root(request)
    body["data"] = {
        "level": result.level,
        "existingPersonId": result.existing_person_id,
        "existingProfileId": result.existing_profile_id,
        "matchReasons": result.match_reasons,
        "candidates": result.candidates,
    }
    return json_response(request, body)


@require_hr_external_permission("hr08.profile.view")
def profile_detail(request, profile_id):
    """GET /api/hr/v1/external-teachers/{id} —— 详情（不含 HIGH_SENSITIVE 字段，§91）。"""
    ctx, err = _ctx(request)
    if err:
        return err

    profile = (
        HrExternalTeacherProfile.objects.filter(tenant_id=ctx.tenant_id, id=profile_id)
        .select_related("person_id", "primary_category")
        .first()
    )
    if profile is None:
        return error_response(request, "EXTERNAL_PROFILE_NOT_FOUND", "外聘档案不存在", 404)

    engs = profile.engagements.filter(tenant_id=ctx.tenant_id).order_by("-start_at")
    body = api_root(request)
    body["data"] = {
        "id": str(profile.id),
        "externalTeacherNo": profile.external_teacher_no,
        "personId": str(profile.person_id_id),
        "legalName": profile.person_id.legal_name,
        "preferredName": profile.person_id.preferred_name,
        "genderCode": profile.person_id.gender_code,
        "genderLabel": (
            {"M": "男", "F": "女", "O": "其他", "U": "未填写"}.get(
                profile.person_id.gender_code, ""
            )
            if profile.person_id.gender_code
            else ""
        ),
        "category": {
            "code": profile.primary_category.code if profile.primary_category else "",
            "name": profile.primary_category.name if profile.primary_category else "",
            "nameLabel": category_label(profile.primary_category.code) if profile.primary_category else "",
        },
        "sourceOrganization": {
            "name": profile.source_organization_name,
            "type": profile.source_organization_type,
            "positionTitle": profile.source_position_title,
        },
        "industryDomain": profile.industry_domain,
        "expertiseTags": profile.expertise_tags or [],
        "highestProfessionalTitle": profile.highest_professional_title,
        "highestSkillLevel": profile.highest_skill_level,
        "teacherQualificationRef": profile.teacher_qualification_ref,
        "ethicsStatus": profile.ethics_status,
        "ethicsStatusLabel": ethics_status_label(profile.ethics_status),
        "identityVerificationStatus": profile.identity_verification_status,
        "identityVerificationStatusLabel": identity_verification_label(profile.identity_verification_status),
        "poolStatus": profile.candidate_pool_status,
        "poolStatusLabel": pool_status_label(profile.candidate_pool_status),
        "currentEngagementStatus": profile.current_engagement_status,
        "currentEngagementStatusLabel": engagement_status_label(profile.current_engagement_status)
        if profile.current_engagement_status
        else "",
        "engagementCount": engs.count(),
        "version": profile.version,
    }
    return json_response(request, body)


@require_hr_external_permission("hr08.profile.view")
def profile_engagements(request, profile_id):
    """GET /api/hr/v1/external-teachers/{id}/engagements —— 受聘历史（§24.4 受聘历史 tab）。"""
    ctx, err = _ctx(request)
    if err:
        return err

    profile = HrExternalTeacherProfile.objects.filter(
        tenant_id=ctx.tenant_id, id=profile_id
    ).first()
    if profile is None:
        return error_response(request, "EXTERNAL_PROFILE_NOT_FOUND", "外聘档案不存在", 404)

    engs = (
        profile.engagements.filter(tenant_id=ctx.tenant_id)
        .order_by("-start_at")
        .select_related("category_id")
    )
    items = []
    for eng in engs:
        items.append(
            {
                "id": str(eng.id),
                "engagementNo": eng.engagement_no,
                "status": eng.status,
                "statusLabel": engagement_status_label(eng.status),
                "category": eng.category_id.code if eng.category_id else "",
                "categoryLabel": category_label(eng.category_id.code) if eng.category_id else "",
                "hostOrganizationId": eng.host_organization_id,
                "startAt": eng.start_at.isoformat(),
                "endAt": eng.end_at.isoformat() if eng.end_at else None,
                "reviewAt": eng.review_at.isoformat() if eng.review_at else None,
                "agreementStatus": eng.agreement_status,
                "agreementStatusLabel": agreement_status_label(eng.agreement_status),
            }
        )
    body = api_root(request)
    body["data"] = {"items": items, "total": len(items)}
    return json_response(request, body)


@require_hr_external_permission("hr08.profile.create")
def import_job_upload(request):
    """
    POST /api/hr/v1/external-teachers/import-jobs  (multipart: file, job_type)
    创建导入 job 并解析 CSV/XLSX 到 staging rows（§110 同链路过账本）。
    """
    ctx, err = _ctx(request)
    if err:
        return err

    job_type = request.POST.get("job_type", "")
    uploaded = request.FILES.get("file")
    if uploaded is None:
        return error_response(request, "INVALID_REQUEST", "缺少 file 字段", 400)

    service = ImportService()
    try:
        job = service.create_job(
            tenant_id=ctx.tenant_id,
            job_type=job_type,
            file_name=uploaded.name or "",
            file_ref="",
            created_by=ctx.user_id,
        )
        content = uploaded.read()
        if uploaded.name.endswith(".csv"):
            service.parse_csv_to_rows(job, content, tenant_id=ctx.tenant_id)
        elif uploaded.name.endswith((".xlsx", ".xls")):
            service.parse_spreadsheet_to_rows(
                job, content, tenant_id=ctx.tenant_id
            )
        else:
            raise ImportValidationError("仅支持 CSV / XLSX")
    except ImportValidationError as exc:
        return error_response(request, "INVALID_REQUEST", str(exc), 400)

    write_external_audit(
        tenant_id=ctx.tenant_id,
        action="ExternalImportUploaded",
        actor_user_id=ctx.user_id,
        business_type="HR08_IMPORT",
        business_id=str(job.id),
        source="api",
    )

    body = api_root(request)
    body["data"] = {"jobId": str(job.id), "totalRows": job.total_rows, "status": job.status}
    return json_response(request, body, status=201)


@require_hr_external_permission("hr08.profile.create")
def import_job_validate(request, job_id):
    """POST /api/hr/v1/external-teachers/import-jobs/{job_id}/validate
    对 PROFILE 类型默认校验：legalName 必填。"""
    ctx, err = _ctx(request)
    if err:
        return err

    job = HrExternalImportJob.objects.filter(tenant_id=ctx.tenant_id, id=job_id).first()
    if job is None:
        return error_response(request, "INVALID_REQUEST", "导入任务不存在", 404)

    def _validate_profile(raw: dict) -> list:
        issues = []
        if not (raw.get("legalName") or "").strip():
            issues.append("legalName:必填")
        if raw.get("documentNumber") and len(str(raw["documentNumber"])) < 6:
            issues.append("documentNumber:证件号过短")
        return issues

    job = ImportService().validate_job(
        job, _validate_profile, tenant_id=ctx.tenant_id
    )
    body = api_root(request)
    body["data"] = {
        "jobId": str(job.id),
        "status": job.status,
        "valid": job.success_count,
        "invalid": job.failed_count,
        "errorSummary": job.error_summary_json,
    }
    return json_response(request, body)


@require_hr_external_permission("hr08.profile.create")
def import_job_confirm(request, job_id):
    """POST /api/hr/v1/external-teachers/import-jobs/{job_id}/confirm
    确认导入：job 置 COMMITTING 并返回 202；真正执行由 job runner 调用 execute（00 §32 不伪装完成）。"""
    ctx, err = _ctx(request)
    if err:
        return err

    job = HrExternalImportJob.objects.filter(tenant_id=ctx.tenant_id, id=job_id).first()
    if job is None:
        return error_response(request, "INVALID_REQUEST", "导入任务不存在", 404)

    job = ImportService().confirm_job(job, tenant_id=ctx.tenant_id)
    body = api_root(request)
    body["data"] = {
        "jobId": str(job.id),
        "status": job.status,
        "note": "已确认，等待异步 execute（生产路径由 job runner 触发）",
    }
    return json_response(request, body, status=202)


@require_hr_external_permission("hr08.profile.create")
def import_job_execute(request, job_id):
    """POST /api/hr/v1/external-teachers/import-jobs/{job_id}/execute
    执行 commit（分批事务 + 结果账本）。
    生产路径应通过异步 job runner 触发；本 endpoint 供可验证/显式执行使用。"""
    ctx, err = _ctx(request)
    if err:
        return err

    job = HrExternalImportJob.objects.filter(tenant_id=ctx.tenant_id, id=job_id).first()
    if job is None:
        return error_response(request, "INVALID_REQUEST", "导入任务不存在", 404)

    try:
        job = ImportService().execute_commit(job, tenant_id=ctx.tenant_id)
    except ImportCommitError as exc:
        return error_response(request, exc.code, str(exc), 409)

    body = api_root(request)
    body["data"] = {
        "jobId": str(job.id),
        "status": job.status,
        "success": job.success_count,
        "failed": job.failed_count,
        "errorSummary": job.error_summary_json,
    }
    return json_response(request, body)


@require_hr_external_permission("hr08.profile.view")
def profile_history(request, profile_id):
    """GET /api/hr/v1/external-teachers/{id}/history —— 履历时间线（事件+聘期，§82）。"""
    ctx, err = _ctx(request)
    if err:
        return err

    profile = HrExternalTeacherProfile.objects.filter(
        tenant_id=ctx.tenant_id, id=profile_id
    ).first()
    if profile is None:
        return error_response(request, "EXTERNAL_PROFILE_NOT_FOUND", "外聘档案不存在", 404)

    events = HrExternalLifecycleEvent.objects.filter(
        tenant_id=ctx.tenant_id,
        engagement_id__external_profile_id=profile,
    ).order_by("-occurred_at")[:200]

    body = api_root(request)
    body["data"] = {
        "events": [
            {
                "eventType": e.event_type,
                "occurredAt": e.occurred_at.isoformat(),
                "effectiveAt": e.effective_at.isoformat() if e.effective_at else None,
                "status": e.status,
                "statusLabel": {
                    "PENDING": "待发布",
                    "PUBLISHED": "已发布",
                    "FAILED": "发布失败",
                    "RETRYING": "重试中",
                }.get(e.status, e.status),
            }
            for e in events
        ]
    }
    return json_response(request, body)
