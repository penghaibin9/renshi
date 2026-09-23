"""Authenticated SELF writes. Identity derives from login + tenant, never payload.

All new write routes are CSRF protected, privilege gated and Authority gated.
Create/upload use durable idempotency receipts; actions use expectedVersion.
"""
import json
import logging
from functools import wraps
from django.core import signing
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import DatabaseError, transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_protect
from hr_self.api import resolve_self_context, HrSelfAccessError
from hr_self.command_contract import (check_object, CommandError, IDENTITY_KEYS,
    SELF_FIELDS, idempotency_key, command_hash)
from hr_self.models import SelfCommandReceipt
from hr_staff.models import (HrStaffMaster, HrCorrectionCase, HrMaterialRequest,
    HrStaffMaterialVersion, HrMaterialSubmission)
from hr_staff.services.authority_mode_service import AuthorityModeService, AuthorityModeError
from hr_staff.services.self_submission_service import SelfCorrectionService, MaterialSubmissionService
from hr_staff.services.correction_service import CorrectionPolicyDenied, CorrectionStateError
from hr_staff.services.correction_fields import CorrectionFieldApplicationError
from hr_staff.services.evidence_reference_service import EvidenceReferenceError
from hr_staff.services.material_service import MaterialService, MaterialAccessDenied
from hr_staff.services.material_file_service import store_staff_material, delete_staff_material, StaffMaterialFileError
from hr_exit.models import RetirementPrecheck
from hr_exit.flex_models import RetirementFlexApplication
from hr_exit.services.flex_service import FlexRetirementService, FlexError
from hr_exit.flex_api import serialize_application
logger = logging.getLogger(__name__)
APPLY_PERMISSION = "hr.self.apply"


def response(data, status=200):
    result = JsonResponse({"apiVersion": "1.0", "schemaVersion": "hr17.commands.1",
        "generatedAt": timezone.now().isoformat(), **data}, status=status)
    result["Cache-Control"] = "no-store"
    return result


def endpoint(*methods):
    def decorate(fn):
        @csrf_protect
        @wraps(fn)
        def wrapped(request, *args, **kwargs):
            if request.method not in methods:
                return response({"error": {"code": "METHOD_NOT_ALLOWED"}}, 405)
            try:
                # Reject identity query overrides even on GET; fail, don't ignore.
                if set(request.GET) & IDENTITY_KEYS:
                    raise CommandError("SELF_IDENTITY_OVERRIDE_FORBIDDEN", "不能指定他人的身份或学校", 403)
                context = resolve_self_context(request)
                if request.method != "GET":
                    try:
                        ticket = signing.loads(request.headers.get("X-HR-Self-Context", ""), salt="hr17-self-command", max_age=900)
                    except signing.BadSignature:
                        raise CommandError("SELF_CONTEXT_EXPIRED", "页面身份凭据过期，请刷新后重新提交", 409) from None
                    if ticket != {"tenant": context.tenant_id, "staff": str(context.staff_id), "user": context.user_id}:
                        raise CommandError("SELF_CONTEXT_CHANGED", "学校或登录身份已切换，未执行此次写入，请重新进入本人服务", 409)
                    if not (request.user.is_superuser or request.user.has_perm(APPLY_PERMISSION)):
                        raise CommandError("PERMISSION_DENIED", "尚未授予本人申请权限，请联系人事管理员", 403)
                    AuthorityModeService().assert_authority_available(context.tenant_id, require_authority=True)
                return fn(request, context, *args, **kwargs)
            except HrSelfAccessError as exc:
                return response({"error": {"code": exc.code, "message": exc.message}}, 403)
            except AuthorityModeError:
                return response({"error": {"code": "AUTHORITY_UNAVAILABLE", "message": "学校尚未完成人事主档权威切换或权威服务不可用，未执行写入"}}, 503)
            except (CommandError, FlexError, EvidenceReferenceError, StaffMaterialFileError) as exc:
                return response({"error": {"code": exc.code, "message": str(exc)}}, exc.status)
            except (CorrectionPolicyDenied, MaterialAccessDenied) as exc:
                return response({"error": {"code": exc.code, "message": str(exc)}}, 403)
            except (CorrectionStateError, CorrectionFieldApplicationError) as exc:
                return response({"error": {"code": exc.code, "message": str(exc)}}, 409)
            except ObjectDoesNotExist:
                return response({"error": {"code": "NOT_FOUND", "message": "当前身份下未找到该记录"}}, 404)
            except (ValueError, TypeError, ValidationError):
                return response({"error": {"code": "INPUT_INVALID", "message": "请求字段格式不正确"}}, 400)
            except DatabaseError:
                logger.exception("HR17 authority/database operation failed")
                return response({"error": {"code": "AUTHORITY_UNAVAILABLE", "message": "数据服务不可用，未报告办理成功，请保留请求编号重试"}}, 503)
        return wrapped
    return decorate


def payload(request, fields):
    if not request.content_type == "application/json" or len(request.body) > 16384:
        raise CommandError("JSON_REQUIRED", "须提交16KB以内JSON对象")
    return check_object(json.loads(request.body or b"{}"), fields)


def correction_payload(case):
    return {"id": str(case.id), "caseNo": case.case_no, "status": case.status,
        "version": case.version, "reason": case.reason, "returnReason": case.return_reason,
        "rejectReason": case.reject_reason, "appliedAt": case.applied_at,
        "source": "HR03", "fields": [i.field_code for i in case.items.all()]}


@transaction.atomic
def once(context, operation, data, execute):
    key = idempotency_key(data.get("idempotencyKey"))
    digest = command_hash(data)
    # Serialize on an existing row, including the first command (no missing-row lock gap).
    HrStaffMaster.objects.select_for_update().get(tenant_id=context.tenant_id, pk=context.staff_id)
    existing = SelfCommandReceipt.objects.filter(tenant_id=context.tenant_id, staff_id=context.staff_id,
        operation=operation, idempotency_key=key).first()
    if existing:
        if existing.request_hash != digest:
            raise CommandError("IDEMPOTENCY_CONFLICT", "同一请求编号不能提交不同内容", 409)
        return existing.result, False
    result = execute()
    # Store only a transport receipt, not another copy of the approval state machine.
    SelfCommandReceipt.objects.create(tenant_id=context.tenant_id, staff_id=context.staff_id,
        operation=operation, idempotency_key=key, request_hash=digest, result=result,
        created_by=context.user_id, updated_by=context.user_id)
    return result, True


@endpoint("GET")
def workspace(request, context):
    query = HrCorrectionCase.objects.filter(tenant_id=context.tenant_id, staff_id=context.staff_id,
        source_channel="SELF").prefetch_related("items").order_by("-created_at")
    try:
        offset = int(request.GET.get("offset", 0))
        if not 0 <= offset <= 10000:
            raise ValueError()
    except ValueError:
        raise CommandError("PAGE_INVALID", "分页位置无效") from None
    corrections = list(query[offset:offset+51])
    requests = list(HrMaterialRequest.objects.filter(tenant_id=context.tenant_id,
        target_staff_id=context.staff_id).order_by("-created_at")[offset:offset+51])
    versions = list(HrStaffMaterialVersion.objects.filter(tenant_id=context.tenant_id,
        material_id__tenant_id=context.tenant_id, material_id__staff_id=context.staff_id,
        uploaded_by=context.user_id, status="CURRENT").select_related("material_id")
        .order_by("-uploaded_at")[offset:offset+51])
    apps = list(RetirementFlexApplication.objects.filter(tenant_id=context.tenant_id,
        staff_id=context.staff_id).order_by("-created_at")[offset:offset+51])
    prechecks = list(RetirementPrecheck.objects.filter(tenant_id=context.tenant_id,
        person_id=context.person_id, decision__in=["ELIGIBLE", "NOT_YET"])
        .order_by("-created_at")[offset:offset+51])
    pending = list(HrMaterialSubmission.objects.filter(tenant_id=context.tenant_id,
        request__target_staff_id=context.staff_id, request__tenant_id=context.tenant_id)
        .order_by("-created_at")[offset:offset+51])
    return response({"data": {"canApply": bool(request.user.is_superuser or request.user.has_perm(APPLY_PERMISSION)),
        "contextToken": signing.dumps({"tenant": context.tenant_id, "staff": str(context.staff_id), "user": context.user_id}, salt="hr17-self-command"),
        "fields": SELF_FIELDS, "corrections": [correction_payload(c) for c in corrections[:50]],
        "materialRequests": [{"id": str(x.id), "status": x.status, "categoryCode": x.required_category_code,
            "instruction": x.instruction, "dueAt": x.due_at} for x in requests[:50]],
        "materials": [{"id": str(v.id), "title": v.material_id.title, "categoryCode": v.material_id.category_code,
            "verificationStatus": v.material_id.verification_status} for v in versions[:50]],
        "submissions": [{"id": str(x.id), "requestId": str(x.request_id), "revision": x.revision,
            "status": x.status, "reviewReason": x.review_reason} for x in pending[:50]],
        "retirementApplications": [serialize_application(x) for x in apps[:50]],
        "prechecks": [{"id": str(x.id), "statutoryDate": x.statutory_date, "decision": x.decision,
            "asOf": x.as_of} for x in prechecks[:50]],
        "offset": offset, "nextOffset": offset+50 if any(len(x)>50 for x in [corrections, requests, versions, apps, prechecks, pending]) else None}})


@endpoint("POST")
def corrections(request, context):
    data = payload(request, {"reason", "items", "evidenceVersionId", "idempotencyKey"})
    def execute():
        case = SelfCorrectionService(context).create_and_submit(reason=data.get("reason"),
            items=data.get("items"), evidence_version_id=data.get("evidenceVersionId"))
        return {"id": str(case.id), "source": "HR03", "receiptKind": "CORRECTION_SUBMITTED"}
    receipt, created = once(context, "CORRECTION", data, execute)
    return response({"data": receipt, "replayed": not created}, 201 if created else 200)


@endpoint("POST")
def correction_action(request, context, case_id):
    data = payload(request, {"action", "expectedVersion", "evidenceVersionId"})
    case = SelfCorrectionService(context).act(case_id, action=data.get("action"),
        version=data.get("expectedVersion"), evidence_version_id=data.get("evidenceVersionId"))
    return response({"data": correction_payload(case)})


@endpoint("POST")
def upload(request, context):
    check_object(dict(request.POST), {"title", "categoryCode", "requestId", "idempotencyKey", "csrfmiddlewaretoken"})
    if set(request.FILES) != {"file"} or len(request.FILES.getlist("file")) != 1:
        raise CommandError("FILE_REQUIRED", "每次请上传一份文件")
    info = store_staff_material(request.FILES["file"], tenant_id=context.tenant_id, staff_id=context.staff_id)
    stored = False
    try:
        data = {"title": request.POST.get("title", ""), "categoryCode": request.POST.get("categoryCode", "OTHER_HR"),
            "requestId": request.POST.get("requestId") or None, "idempotencyKey": request.POST.get("idempotencyKey"),
            "sha256": info["sha256"], "sizeBytes": info["size_bytes"]}
        def execute():
            material = MaterialService(context.tenant_id, context.user_id).create_material(staff_id=context.staff_id,
                category_code=data["categoryCode"], title=data["title"],
                sensitivity_level="HIGH_SENSITIVE" if data["categoryCode"] == "IDENTITY" else "SENSITIVE", **info)
            receipt = {"materialId": str(material.id), "versionId": str(material.current_version_id),
                "receiptKind": "MATERIAL_UNVERIFIED", "source": "HR03"}
            if data["requestId"]:
                item = MaterialSubmissionService(context.tenant_id, context.user_id).submit(request_id=data["requestId"],
                    staff_id=context.staff_id, material_version_id=material.current_version_id)
                receipt["submissionId"] = str(item.id)
            return receipt
        receipt, created = once(context, "MATERIAL_UPLOAD", data, execute)
        stored = created
        return response({"data": receipt, "replayed": not created}, 201 if created else 200)
    finally:
        if not stored:
            delete_staff_material(info["storage_file_id"], tenant_id=context.tenant_id, staff_id=context.staff_id)


@endpoint("POST")
def flex_create(request, context):
    data = payload(request, {"precheckId", "mode", "requestedDate", "reason", "parentApplicationId", "idempotencyKey"})
    idempotency_key(data.get("idempotencyKey"))
    item, created = FlexRetirementService(context.tenant_id, context.user_id).create(staff_id=context.staff_id,
        precheck_id=data.get("precheckId"), mode=data.get("mode"), requested_date=data.get("requestedDate"),
        reason=data.get("reason"), idempotency_key=data.get("idempotencyKey"), parent_id=data.get("parentApplicationId"))
    return response({"data": serialize_application(item), "replayed": not created}, 201 if created else 200)


@endpoint("POST")
def flex_action(request, context, application_id):
    data = payload(request, {"action", "expectedVersion", "noticeVersionId"})
    service = FlexRetirementService(context.tenant_id, context.user_id)
    if data.get("action") == "SUBMIT":
        item = service.submit(application_id, staff_id=context.staff_id,
            expected_version=data.get("expectedVersion"), notice_version_id=data.get("noticeVersionId"))
    elif data.get("action") == "CANCEL":
        item = service.cancel(application_id, staff_id=context.staff_id, expected_version=data.get("expectedVersion"))
    else:
        raise CommandError("ACTION_INVALID", "不支持的本人操作")
    return response({"data": serialize_application(item)})
