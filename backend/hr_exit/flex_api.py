"""HR16 manager authority endpoints; SELF endpoints live under HR17."""
import json
import logging
from functools import wraps
from django.core.exceptions import ValidationError
from django.db import DatabaseError, transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_protect
from hr_exit.api import resolve_request_tenant, HrExitAccessError
from hr_exit.flex_models import RetirementFlexApplication, RetirementFlexEvent
from hr_exit.services.flex_service import FlexRetirementService, FlexError
from hr_exit.services.case_service import ExitCaseError
from hr_staff.constants import MaterialCategoryCode
from hr_staff.services.evidence_reference_service import EvidenceReferenceError
from hr_staff.services.material_file_service import store_staff_material, delete_staff_material, StaffMaterialFileError
from hr_staff.services.material_service import MaterialService, MaterialAccessDenied
from hr_self.command_contract import CommandError, check_object
logger = logging.getLogger(__name__)


def serialize_application(item):
    return {"id": str(item.id), "mode": item.mode, "status": item.status, "version": item.version,
        "requestedDate": item.requested_date, "statutoryDate": item.authority_snapshot.get("statutoryDate"),
        "noticeDate": item.notice_date, "reason": item.reason, "precheckId": str(item.precheck_id),
        "parentId": str(item.parent_application_id) if item.parent_application_id else None,
        "exitCaseId": str(item.exit_case_id) if item.exit_case_id else None,
        "approvedAt": item.approved_at, "approvalHash": item.approval_hash}


def answer(data, status=200):
    response = JsonResponse({"apiVersion": "1.0", "schemaVersion": "hr16.flex.1", **data}, status=status)
    response["Cache-Control"] = "no-store"
    return response


def managed(*methods):
    def decorate(fn):
        @csrf_protect
        @wraps(fn)
        def wrapped(request, *args, **kwargs):
            if request.method not in methods:
                return answer({"error": {"code": "METHOD_NOT_ALLOWED"}}, 405)
            try:
                tenant = resolve_request_tenant(request, required_permission="hr.exit.flex.review")
                return fn(request, tenant, *args, **kwargs)
            except HrExitAccessError as exc:
                return answer({"error": {"code": exc.code, "message": exc.message}}, 403)
            except (FlexError, EvidenceReferenceError, CommandError, StaffMaterialFileError) as exc:
                return answer({"error": {"code": exc.code, "message": str(exc)}}, exc.status)
            except (ExitCaseError, MaterialAccessDenied) as exc:
                return answer({"error": {"code": exc.code, "message": str(exc)}}, 409)
            except (ValueError, TypeError, ValidationError):
                return answer({"error": {"code": "INPUT_INVALID", "message": "请求格式无效"}}, 400)
            except DatabaseError:
                logger.exception("HR16 flexible retirement authority failure")
                return answer({"error": {"code": "AUTHORITY_UNAVAILABLE", "message": "数据服务不可用，未报告审批成功"}}, 503)
        return wrapped
    return decorate


def body(request, fields):
    if request.content_type != "application/json" or len(request.body) > 16384:
        raise CommandError("JSON_REQUIRED", "须提交16KB以内JSON对象")
    return check_object(json.loads(request.body or b"{}"), fields)


@managed("GET")
def applications(request, tenant):
    from hr_staff.models import HrStaffMaster
    offset = int(request.GET.get("offset", 0))
    if not 0 <= offset <= 10000:
        raise ValueError()
    query = RetirementFlexApplication.objects.filter(tenant_id=tenant).order_by("-created_at")
    status = request.GET.get("status", "")
    if status:
        if status not in RetirementFlexApplication.Status.values:
            raise ValueError()
        query = query.filter(status=status)
    rows = list(query[offset:offset+51])
    names = {s.id: {"staffNo": s.staff_no, "name": s.person_id.legal_name} for s in
        HrStaffMaster.objects.filter(tenant_id=tenant, id__in=[x.staff_id for x in rows]).select_related("person_id")}
    return answer({"data": {"items": [{**serialize_application(x), **names.get(x.staff_id, {})} for x in rows[:50]],
        "nextOffset": offset+50 if len(rows)>50 else None}})


@managed("GET")
def detail(request, tenant, application_id):
    from hr_staff.models import HrStaffMaterialVersion
    item = RetirementFlexApplication.objects.filter(tenant_id=tenant, pk=application_id).first()
    if not item:
        raise FlexError("FLEX_NOT_FOUND", "未找到申请", 404)
    versions = list(HrStaffMaterialVersion.objects.filter(tenant_id=tenant, material_id__tenant_id=tenant,
        material_id__staff_id=item.staff_id, status="CURRENT").select_related("material_id").order_by("-uploaded_at")[:101])
    events = list(RetirementFlexEvent.objects.filter(tenant_id=tenant, application_id=item.id)
        .order_by("-version")[:101])
    from hr_exit.models import ExitFact, RetirementFact
    exits = list(ExitFact.objects.filter(tenant_id=tenant, source_case_id=item.exit_case_id,
        status__in=["EFFECTIVE", "REVISED", "REVOKED"]).order_by("created_at")[:100]) if item.exit_case_id else []
    retired = {str(x.exit_fact_id): str(x.id) for x in RetirementFact.objects.filter(tenant_id=tenant,
        exit_fact_id__in=[x.id for x in exits])}
    return answer({"data": {**serialize_application(item), "staffId": str(item.staff_id),
        "canEffect": bool(request.user.is_superuser or request.user.has_perm("hr.exit.effect")),
        "formalExits": [{"id": str(x.id), "factNo": x.fact_no, "effectiveDate": x.employment_end_date,
            "retirementFactId": retired.get(str(x.id))} for x in exits],
        "review": item.review_snapshot, "authority": item.authority_snapshot,
        "materials": [{"id": str(v.id), "materialId": str(v.material_id_id), "title": v.material_id.title,
            "categoryCode": v.material_id.category_code, "verificationStatus": v.material_id.verification_status,
            "sha256": v.sha256} for v in versions[:100]], "materialsTruncated": len(versions)>100,
        "events": [{"version": e.version, "action": e.action, "at": e.created_at, "detail": e.payload.get("detail", {})} for e in events[:100]],
        "eventsTruncated": len(events)>100}})


@managed("POST")
def review(request, tenant, application_id):
    data = body(request, {"action", "expectedVersion", "reason", "review"})
    if data.get("review") is not None:
        check_object(data["review"], {"capacity", "contributionMonths", "agreementDate", "approvalMaterialVersionId",
            "contributionMaterialVersionId", "agreementMaterialVersionId"})
    item = FlexRetirementService(tenant, request.user.id).review(application_id, expected_version=data.get("expectedVersion"),
        action=data.get("action"), reason=data.get("reason"), review=data.get("review"))
    return answer({"data": serialize_application(item)})


@managed("POST")
def open_exit_case(request, tenant, application_id):
    resolve_request_tenant(request, required_permission="hr.exit.manage")
    data = body(request, {"expectedVersion"})
    item = FlexRetirementService(tenant, request.user.id).open_exit_case(application_id,
        expected_version=data.get("expectedVersion"))
    return answer({"data": serialize_application(item)})


@managed("POST")
def upload_evidence(request, tenant, application_id):
    resolve_request_tenant(request, required_permission="hr.staff.material.upload")
    check_object(dict(request.POST), {"title", "categoryCode", "csrfmiddlewaretoken"})
    if set(request.FILES) != {"file"} or len(request.FILES.getlist("file")) != 1:
        raise CommandError("FILE_REQUIRED", "请选择一份核验材料")
    app = RetirementFlexApplication.objects.filter(tenant_id=tenant, pk=application_id).first()
    if not app or app.status != "SUBMITTED":
        raise FlexError("FLEX_STATE_CONFLICT", "只能为待审批申请补充核验材料", 409)
    category_code = str(request.POST.get("categoryCode") or "").strip().upper()
    allowed_categories = {
        MaterialCategoryCode.RETIREMENT_APPROVAL,
        MaterialCategoryCode.RETIREMENT_CONTRIBUTION,
        MaterialCategoryCode.RETIREMENT_AGREEMENT,
    }
    if category_code not in allowed_categories:
        raise CommandError(
            "RETIREMENT_EVIDENCE_CATEGORY_REQUIRED",
            "核验材料必须明确选择审批依据、社保缴费凭据或双方书面协议",
        )
    info = store_staff_material(request.FILES["file"], tenant_id=tenant, staff_id=app.staff_id)
    saved = False
    try:
        with transaction.atomic():
            locked = RetirementFlexApplication.objects.select_for_update().get(tenant_id=tenant, pk=application_id)
            if locked.status != "SUBMITTED":
                raise FlexError("FLEX_STATE_CONFLICT", "审批状态已变化，请刷新", 409)
            material = MaterialService(tenant, request.user.id).create_material(staff_id=app.staff_id,
                category_code=category_code, title=request.POST.get("title", ""), sensitivity_level="SENSITIVE", **info)
        saved = True
        return answer({"data": {"materialId": str(material.id), "versionId": str(material.current_version_id)}}, 201)
    finally:
        if not saved:
            delete_staff_material(info["storage_file_id"], tenant_id=tenant, staff_id=app.staff_id)
