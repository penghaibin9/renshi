import json
from django.db import DatabaseError
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_protect
from hr_data.api import resolve_request_tenant, HrDataAccessError, _error
from hr_data.operational_models import OperationalSnapshot
from hr_data.services.operational_snapshot_service import OperationalSnapshotService
from hr_self.command_contract import CommandError, check_object

def answer(data, status=200):
    response = JsonResponse({"apiVersion": "1.0", "schemaVersion": "hr18.operations.1", "data": data}, status=status)
    response["Cache-Control"] = "no-store"
    return response

@csrf_protect
def snapshots(request, snapshot_id=None):
    if request.method not in {"GET", "POST"} or (snapshot_id and request.method != "GET"):
        return _error("METHOD_NOT_ALLOWED", status=405)
    try:
        tenant = resolve_request_tenant(request, required_permission="hr.data.snapshot.capture" if request.method == "POST" else "hr.data.view")
        service = OperationalSnapshotService(tenant, request.user.id)
        if snapshot_id:
            item = OperationalSnapshot.objects.filter(tenant_id=tenant, pk=snapshot_id).first()
            if not item:
                return _error("NOT_FOUND", "本校未找到该快照", status=404)
            if item.compute_hash() != item.evidence_hash:
                return _error("SNAPSHOT_HASH_MISMATCH", "快照完整性校验失败，不能用于报送", status=409)
            return answer({"id": str(item.id), "createdAt": item.created_at, "evidenceHash": item.evidence_hash,
                "payload": item.payload})
        if request.method == "POST":
            if request.content_type != "application/json" or len(request.body) > 4096:
                raise ValueError()
            data = check_object(json.loads(request.body or b"{}"), {"idempotencyKey"})
            item, created = service.capture(data.get("idempotencyKey"))
            return answer({"id": str(item.id), "createdAt": item.created_at, "evidenceHash": item.evidence_hash,
                "payload": item.payload, "replayed": not created}, 201 if created else 200)
        offset = int(request.GET.get("offset", 0))
        if not 0 <= offset <= 10000:
            raise ValueError()
        history = list(OperationalSnapshot.objects.filter(tenant_id=tenant).defer("payload").order_by("-created_at")[offset:offset+21])
        return answer({"current": service.observe(), "canCapture": bool(request.user.is_superuser or request.user.has_perm("hr.data.snapshot.capture")),
            "history": [{"id": str(x.id), "createdAt": x.created_at, "evidenceHash": x.evidence_hash} for x in history[:20]],
            "nextOffset": offset+20 if len(history)>20 else None})
    except HrDataAccessError as exc:
        return _error(exc.code, exc.message, status=403)
    except CommandError as exc:
        return _error(exc.code, str(exc), status=exc.status)
    except (ValueError, TypeError):
        return _error("INPUT_INVALID", "请求格式或分页参数无效", status=400)
    except DatabaseError:
        return _error("SOURCE_UNAVAILABLE", "数据源当前不可用，没有生成成功回执", status=503)
