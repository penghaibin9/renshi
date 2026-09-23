"""Stable ports from HR01-HR18 to school-specific configuration/integrations.

Business modules must not read ``hr_configuration`` or ``hr_integration`` tables
directly.  Keeping these two calls stable means a new school changes published
configuration, mapping profiles and Adapter instances rather than forking HR01-HR18.
"""
from __future__ import annotations

from hr_configuration.services import get_published_workflow_config
from hr_integration.services import connection_contract


def school_workflow(*, tenant_id: int, business_domain: str, workflow_code: str | None = None) -> dict | None:
    return get_published_workflow_config(
        tenant_id=tenant_id, business_domain=business_domain, workflow_code=workflow_code
    )


def school_integration(*, tenant_id: int, category: str, code: str | None = None) -> dict | None:
    return connection_contract(tenant_id=tenant_id, category=category, code=code)
