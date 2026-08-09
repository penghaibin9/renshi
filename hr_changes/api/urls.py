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
]
