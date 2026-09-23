from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.db.migrations.recorder import MigrationRecorder

from hr_configuration.management.commands.bootstrap_hr_configuration_v1 import DEFAULTS
from hr_configuration.models import WorkflowDefinition, WorkflowVersion
from hr_integration.models import IntegrationConnection, IntegrationFieldMapping, SsoLoginEvidence
from hr_integration.services import connection_contract
from hr_integration.sso_runtime import runtime_contract_hash


class Command(BaseCommand):
    help = "Verify one school's Configuration Center V1 + Integration Hub V1 implementation on real MySQL 8.4."

    def add_arguments(self, parser):
        parser.add_argument("--tenant", type=int, required=True)
        parser.add_argument("--require-published", action="append", default=[], metavar="HRxx")
        parser.add_argument("--require-verified", action="append", default=[], metavar="CATEGORY")
        parser.add_argument("--require-mapping", action="store_true")
        parser.add_argument("--require-sso-runtime", action="store_true")
        parser.add_argument("--json-output", default="")

    def handle(self, *args, **options):
        tenant_id = int(options["tenant"])
        if tenant_id <= 0:
            raise CommandError("--tenant must be positive")
        if connection.vendor != "mysql":
            raise CommandError(f"MYSQL_REQUIRED: current database vendor is {connection.vendor}")

        with connection.cursor() as cursor:
            cursor.execute("SELECT VERSION()")
            mysql_version = str(cursor.fetchone()[0])
        if not mysql_version.startswith("8.4."):
            raise CommandError(f"MYSQL_84_REQUIRED: current server is {mysql_version}")

        applied = set(MigrationRecorder(connection).applied_migrations())
        required_migrations = {("hr_configuration", "0001_initial"), ("hr_integration", "0001_initial"), ("hr_integration", "0002_ssologinevidence"), ("hr_integration", "0003_ssologinevidence_runtime_contract_hash")}
        missing_migrations = sorted(required_migrations - applied)
        if missing_migrations:
            raise CommandError(f"MIGRATION_MISSING: {missing_migrations}")

        expected = {domain: code for domain, (code, _name, _stages) in DEFAULTS.items()}
        workflows = WorkflowDefinition.objects.filter(tenant_id=tenant_id, code__in=expected.values())
        found_codes = set(workflows.values_list("code", flat=True))
        missing_codes = sorted(set(expected.values()) - found_codes)
        if missing_codes:
            raise CommandError("BOOTSTRAP_INCOMPLETE: " + ", ".join(missing_codes))

        duplicate_codes = sorted(
            code for code in expected.values()
            if WorkflowDefinition.objects.filter(tenant_id=tenant_id, code=code).count() != 1
        )
        if duplicate_codes:
            raise CommandError("BOOTSTRAP_DUPLICATE: " + ", ".join(duplicate_codes))

        published_by_domain = {}
        for domain, code in expected.items():
            workflow = WorkflowDefinition.objects.get(tenant_id=tenant_id, code=code)
            published_by_domain[domain] = workflow.versions.filter(status=WorkflowVersion.Status.PUBLISHED).count()

        requested_published = {str(x).upper() for x in options["require_published"]}
        unknown_domains = sorted(requested_published - set(expected))
        if unknown_domains:
            raise CommandError("UNKNOWN_PUBLISHED_DOMAIN: " + ", ".join(unknown_domains))
        missing_published = sorted(domain for domain in requested_published if published_by_domain[domain] < 1)
        if missing_published:
            raise CommandError("PUBLISHED_CONFIG_REQUIRED: " + ", ".join(missing_published))

        category_counts = {}
        verified_categories = set()
        for row in IntegrationConnection.objects.filter(tenant_id=tenant_id):
            category_counts[row.category] = category_counts.get(row.category, 0) + 1
            if row.enabled and row.status == IntegrationConnection.Status.VERIFIED:
                verified_categories.add(row.category)
                contract = connection_contract(tenant_id=tenant_id, category=row.category, code=row.code)
                if not contract or len(contract.get("contractHash", "")) != 64:
                    raise CommandError(f"INTEGRATION_CONTRACT_INVALID: {row.code}")
                serialized = json.dumps(contract, ensure_ascii=False, sort_keys=True)
                if row.secret_ciphertext and row.secret_ciphertext in serialized:
                    raise CommandError(f"INTEGRATION_SECRET_LEAK: {row.code}")

        requested_verified = {str(x).upper() for x in options["require_verified"]}
        missing_verified = sorted(requested_verified - verified_categories)
        if missing_verified:
            raise CommandError("VERIFIED_INTEGRATION_REQUIRED: " + ", ".join(missing_verified))

        sso_success_count = 0
        for sso_connection in IntegrationConnection.objects.filter(tenant_id=tenant_id, category=IntegrationConnection.Category.SSO, enabled=True):
            current_hash = runtime_contract_hash(sso_connection)
            sso_success_count += SsoLoginEvidence.objects.filter(
                tenant_id=tenant_id, connection=sso_connection, status=SsoLoginEvidence.Status.SUCCESS,
                runtime_contract_hash=current_hash,
            ).count()
        if options["require_sso_runtime"] and sso_success_count < 1:
            raise CommandError("SSO_RUNTIME_LOGIN_EVIDENCE_REQUIRED_FOR_CURRENT_CONTRACT")

        mapping_count = IntegrationFieldMapping.objects.filter(
            tenant_id=tenant_id,
            profile__connection__tenant_id=tenant_id,
            profile__connection__enabled=True,
        ).count()
        if options["require_mapping"] and mapping_count < 1:
            raise CommandError("FIELD_MAPPING_REQUIRED")

        result = {
            "status": "PASS",
            "tenantId": tenant_id,
            "databaseVendor": connection.vendor,
            "mysqlVersion": mysql_version,
            "migrations": {"hr_configuration": "0001_initial", "hr_integration": "0003_ssologinevidence_runtime_contract_hash"},
            "workflowCount": len(expected),
            "publishedByDomain": published_by_domain,
            "integrationConnectionCount": sum(category_counts.values()),
            "verifiedCategories": sorted(verified_categories),
            "fieldMappingCount": mapping_count,
            "ssoRuntimeSuccessCount": sso_success_count,
        }
        rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
        if options["json_output"]:
            path = Path(options["json_output"])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(rendered + "\n", encoding="utf-8")
        self.stdout.write(rendered)
        self.stdout.write(self.style.SUCCESS("HR Configuration V1 + Integration Hub V1 gate: PASS"))
