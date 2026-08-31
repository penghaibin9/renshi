"""
hr_changes/api/views.py —— HR06 API 视图（S1）。

S1：contract 探针 + bootstrap（动作/原因/受管字段/状态元数据）。
"""

from __future__ import annotations

from django.views.decorators.http import require_GET

from hr_changes.api.base import (
    api_root,
    error_response,
    json_response,
    make_hr_change_context,
)
from hr_changes.context import HrChangeContextError
from hr_changes.permissions import require_hr_change_permission
from hr_changes.selectors.bootstrap_data import BootstrapDataSelector

SCHEMA_CONTRACT = "hr06.contract.1"
SCHEMA_BOOTSTRAP = "hr06.bootstrap.1"


@require_GET
def contract_probe(request):
    """API 契约探针：校验 URL 前缀可用。"""
    payload = api_root(request)
    payload["schemaVersion"] = SCHEMA_CONTRACT
    payload["data"] = {"status": "ok", "module": "hr06"}
    return json_response(request, payload)


@require_GET
@require_hr_change_permission("hr.change.view")
def bootstrap(request):
    try:
        context = make_hr_change_context(request)
    except HrChangeContextError as exc:
        return error_response(request, exc.code, exc.message, status=403)
    selector = BootstrapDataSelector(context.tenant_id)
    payload = api_root(request)
    payload["schemaVersion"] = SCHEMA_BOOTSTRAP
    payload["data"] = selector.all()
    return json_response(request, payload)
