#!/usr/bin/env python3
"""Database-side acceptance assertions for the V1 configuration/integration gate."""
from __future__ import annotations

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "horilla.settings")

import django  # noqa: E402

django.setup()

from hr_configuration.models import (  # noqa: E402
    ApprovalRoleRule,
    ConditionRule,
    ExcelColumn,
    ExcelTemplate,
    FieldDefinition,
    NotificationRule,
    PrintTemplate,
    WorkflowDefinition,
    WorkflowVersion,
)
from hr_integration.models import IntegrationConnection, IntegrationFieldMapping  # noqa: E402
from hr_integration.services import connection_contract  # noqa: E402


def require(value, message: str) -> None:
    if not value:
        raise AssertionError(message)


def main() -> None:
    tenant_id = int(os.environ["HR_V1_TENANT_ID"])
    require(WorkflowDefinition.objects.filter(tenant_id=tenant_id).count() == 8, "expected exactly eight V1 workflow shells")
    onboarding = WorkflowDefinition.objects.get(tenant_id=tenant_id, code="ONBOARDING")
    version = onboarding.versions.get(status=WorkflowVersion.Status.PUBLISHED)
    require(len(version.content_hash) == 64, "published configuration hash missing")
    require(FieldDefinition.objects.filter(version=version, key="STAFF_NO").exists(), "STAFF_NO field missing")
    require(ApprovalRoleRule.objects.filter(version=version).exists(), "approval role missing")
    require(ConditionRule.objects.filter(version=version).exists(), "condition missing")
    require(NotificationRule.objects.filter(version=version).exists(), "notification missing")
    require(PrintTemplate.objects.filter(version=version).exists(), "print template missing")
    excel = ExcelTemplate.objects.get(version=version, code="ONBOARDING_IMPORT")
    require(ExcelColumn.objects.filter(template=excel, field_key="STAFF_NO").exists(), "Excel column missing")

    connection = IntegrationConnection.objects.get(tenant_id=tenant_id, code="MASTERDATA_CI")
    require(connection.status == IntegrationConnection.Status.VERIFIED, f"connection not VERIFIED: {connection.status}")
    require(connection.secret_ciphertext and "CI-TOP-SECRET" not in connection.secret_ciphertext, "credential is not encrypted")
    require(IntegrationFieldMapping.objects.filter(profile__connection=connection, source_field="employeeNo", target_field="STAFF_NO").exists(), "field mapping missing")
    contract = connection_contract(tenant_id=tenant_id, category="MASTER_DATA", code="MASTERDATA_CI")
    require(contract and len(contract["contractHash"]) == 64, "integration contract missing")
    require("CI-TOP-SECRET" not in str(contract), "secret leaked into contract")
    print("HR Configuration V1 + Integration Hub V1 database acceptance: PASS")


if __name__ == "__main__":
    main()
