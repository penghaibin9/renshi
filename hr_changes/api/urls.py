"""
hr_changes/api/urls.py —— HR06 API 路由。

前缀：/api/hr/v1/changes/*
- S1: contract 探针 + bootstrap
- S3: changes CRUD + workflow 动作
- S4: transfers
- S5: identity-changes
- S6: temporary
- S7: ledger / corrections / rescinds
- S8: bulk
"""

from django.urls import path

from hr_changes.api import changes as changes_api
from hr_changes.api import transfers as transfers_api
from hr_changes.api import views as api_views

urlpatterns = [
    path(
        "api/hr/v1/changes/contract",
        api_views.contract_probe,
        name="hr06-api-contract",
    ),
    path(
        "api/hr/v1/changes/bootstrap",
        api_views.bootstrap,
        name="hr06-api-bootstrap",
    ),
    # ---- S3 案件 CRUD + 动作 ----
    path(
        "api/hr/v1/changes",
        changes_api.change_list,
        name="hr06-api-changes-list",
    ),
    path(
        "api/hr/v1/changes/future",
        changes_api.future_changes,
        name="hr06-api-changes-future",
    ),
    path(
        "api/hr/v1/changes/<uuid:case_id>",
        changes_api.change_detail,
        name="hr06-api-changes-detail",
    ),
    path(
        "api/hr/v1/changes/<uuid:case_id>/validate",
        changes_api.change_validate,
        name="hr06-api-changes-validate",
    ),
    path(
        "api/hr/v1/changes/<uuid:case_id>/preview",
        changes_api.change_preview,
        name="hr06-api-changes-preview",
    ),
    path(
        "api/hr/v1/changes/<uuid:case_id>/<str:action>",
        changes_api.change_action,
        name="hr06-api-changes-action",
    ),
    # ---- S4 校内调动 ----
    path(
        "api/hr/v1/changes/transfers",
        transfers_api.transfer_list,
        name="hr06-api-transfers-list",
    ),
    path(
        "api/hr/v1/changes/transfers/<uuid:case_id>",
        transfers_api.transfer_detail,
        name="hr06-api-transfers-detail",
    ),
    path(
        "api/hr/v1/changes/transfers/<uuid:case_id>/reserve",
        transfers_api.transfer_reserve,
        name="hr06-api-transfers-reserve",
    ),
    path(
        "api/hr/v1/changes/transfers/<uuid:case_id>/release",
        transfers_api.transfer_release,
        name="hr06-api-transfers-release",
    ),
]
