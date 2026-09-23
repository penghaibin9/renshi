import json
from django.core.exceptions import ValidationError
from django.db import DatabaseError
from django.views.decorators.csrf import csrf_protect
from hr_staff.api.base import make_staff_context, error_response, json_response, api_root
from hr_staff.context import HrStaffContextError
from hr_staff.permissions import require_hr_staff_permission
from hr_staff.policies.scope_policy import ScopeEnforcer, StaffNotFound, StaffScopeDenied
from hr_staff.models import HrMaterialSubmission
from hr_staff.services.self_submission_service import MaterialSubmissionService
from hr_staff.services.correction_service import CorrectionPolicyDenied
from hr_staff.services.evidence_reference_service import EvidenceReferenceError
from hr_staff.services.material_service import MaterialAccessDenied, MaterialVersionConflict
from hr_self.command_contract import check_object, CommandError

@csrf_protect
@require_hr_staff_permission("hr.staff.material.verify")
def submissions(request, staff_id, submission_id=None):
    if request.method not in {"GET", "POST"} or (request.method == "POST" and submission_id is None):
        return error_response(request, "METHOD_NOT_ALLOWED", "方法不支持", 405)
    try:
        context = make_staff_context(request)
        ScopeEnforcer(context).get_staff_or_deny(staff_id)
        query = HrMaterialSubmission.objects.filter(tenant_id=context.tenant_id,
            request__tenant_id=context.tenant_id, request__target_staff_id=staff_id)
        if request.method == "POST":
            if not query.filter(pk=submission_id).exists():
                raise CommandError("NOT_FOUND", "本校本人员未找到该回执", 404)
            if request.content_type != "application/json" or len(request.body)>4096:
                raise ValueError()
            data = check_object(json.loads(request.body or b"{}"), {"action", "reason"})
            item = MaterialSubmissionService(context.tenant_id, request.user.id).review(
                submission_id=submission_id, action=data.get("action"), reason=data.get("reason"))
            return json_response(request, {**api_root(request), "data": {"id": str(item.id), "status": item.status}})
        offset = int(request.GET.get("offset", 0))
        if not 0 <= offset <= 10000:
            raise ValueError()
        rows = list(query.select_related("request", "material_version__material_id").order_by("-created_at")[offset:offset+51])
        return json_response(request, {**api_root(request), "data": {"items": [{"id": str(x.id),
            "title": x.material_version.material_id.title, "materialId": str(x.material_version.material_id_id),
            "materialVersionId": str(x.material_version_id), "requestId": str(x.request_id),
            "revision": x.revision, "status": x.status, "reviewReason": x.review_reason,
            "createdAt": x.created_at} for x in rows[:50]], "nextOffset": offset+50 if len(rows)>50 else None}})
    except HrStaffContextError as exc:
        return error_response(request, exc.code, exc.message, exc.status)
    except (StaffNotFound, StaffScopeDenied, CorrectionPolicyDenied) as exc:
        return error_response(request, exc.code, "资料不存在或当前角色无权处理", 403)
    except (MaterialAccessDenied, MaterialVersionConflict) as exc:
        return error_response(request, exc.code, "材料状态已变化或当前身份无权验收", 409)
    except (CommandError, EvidenceReferenceError) as exc:
        return error_response(request, exc.code, str(exc), exc.status)
    except (ValueError, TypeError, ValidationError):
        return error_response(request, "INPUT_INVALID", "请求格式无效", 400)
    except DatabaseError:
        return error_response(request, "AUTHORITY_UNAVAILABLE", "材料服务不可用，未报告验收成功", 503)
