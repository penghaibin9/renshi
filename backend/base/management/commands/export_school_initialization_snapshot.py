"""Export a secret-free school initialization snapshot for procurement acceptance."""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from django.apps import apps
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand, CommandError
from django.db.migrations.recorder import MigrationRecorder
from django.forms.models import model_to_dict
from django.utils import timezone

SENSITIVE_TOKENS = ("password", "secret", "token", "private", "credential", "api_key", "apikey")
SAFE_DICTIONARY_MODELS = (
    ("base", "Company"),
    ("base", "Department"),
    ("base", "JobPosition"),
    ("base", "JobRole"),
    ("base", "EmployeeType"),
    ("base", "WorkType"),
    ("base", "EmployeeShift"),
)
SAFE_SETTING_NAMES = (
    "LANGUAGE_CODE",
    "TIME_ZONE",
    "COMPANY_SCOPED_PERMISSIONS",
    "TENANT_FAIL_CLOSED",
    "TWO_FACTORS_AUTHENTICATION",
    "MFA_OTP_TTL_SECONDS",
    "MFA_OTP_MAX_ATTEMPTS",
)


def _json_value(value):
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (UUID, Decimal, Path)):
        return str(value)
    if isinstance(value, (set, tuple, list)):
        return [_json_value(v) for v in value]
    # Django FieldFile and similar storage-backed values expose a stable name.
    name = getattr(value, "name", None)
    if isinstance(name, str):
        return name
    # Initialization evidence must remain JSON serializable even if a safe
    # dictionary model later adds a custom scalar field type.
    return str(value)


def _safe_model_rows(model):
    rows = []
    scalar_names = []
    for field in model._meta.fields:
        name = field.name
        if any(token in name.lower() for token in SENSITIVE_TOKENS):
            continue
        if name in {"employee", "employee_id", "user", "user_id"}:
            continue
        scalar_names.append(name)
    for obj in model._base_manager.all().order_by(model._meta.pk.name):
        row = {}
        for name in scalar_names:
            value = getattr(obj, name, None)
            if hasattr(value, "pk"):
                value = value.pk
            row[name] = _json_value(value)
        rows.append(row)
    return rows


class Command(BaseCommand):
    help = "Export a secret-free school initialization/configuration snapshot."

    def add_arguments(self, parser):
        parser.add_argument("--output", required=True)
        parser.add_argument("--operator", required=True)

    def handle(self, *args, **options):
        output = Path(options["output"]).expanduser().resolve()
        if output.suffix.lower() != ".json":
            raise CommandError("--output must end with .json")
        output.parent.mkdir(parents=True, exist_ok=True)

        dictionaries = {}
        for app_label, model_name in SAFE_DICTIONARY_MODELS:
            try:
                model = apps.get_model(app_label, model_name)
            except LookupError:
                continue
            dictionaries[f"{app_label}.{model_name}"] = _safe_model_rows(model)

        roles = []
        for group in Group.objects.prefetch_related("permissions__content_type").order_by("name"):
            roles.append(
                {
                    "id": group.pk,
                    "name": group.name,
                    "permissions": sorted(
                        f"{perm.content_type.app_label}.{perm.codename}"
                        for perm in group.permissions.all()
                    ),
                    "memberCount": group.user_set.count(),
                }
            )

        User = get_user_model()
        admins = []
        for user in User._default_manager.filter(is_active=True).filter(is_staff=True).order_by("pk"):
            admins.append(
                {
                    "id": user.pk,
                    "username": getattr(user, "username", ""),
                    "email": getattr(user, "email", ""),
                    "isStaff": bool(getattr(user, "is_staff", False)),
                    "isSuperuser": bool(getattr(user, "is_superuser", False)),
                }
            )

        mappings = []
        try:
            mapping_model = apps.get_model("hr_data", "ExchangeTargetMappingVersion")
            for row in mapping_model._base_manager.all().order_by("tenant_id", "target_code", "version_no"):
                mappings.append(
                    {
                        "id": row.pk,
                        "tenantId": row.tenant_id,
                        "targetCode": row.target_code,
                        "versionNo": row.version_no,
                        "datasetCode": row.dataset_code,
                        "datasetVersion": row.dataset_version,
                        "transportKind": row.transport_kind,
                        "providerKey": row.provider_key,
                        "mapping": row.mapping_json,
                        "expectedReceipt": row.expected_receipt,
                    }
                )
        except LookupError:
            pass

        migration_rows = [
            {"app": app, "name": name, "appliedAt": applied.isoformat() if applied else None}
            for app, name, applied in MigrationRecorder.Migration.objects.order_by("app", "name").values_list("app", "name", "applied")
        ]

        payload = {
            "schemaVersion": 1,
            "kind": "YUEKE_UNIVERSITY_HR_SCHOOL_INITIALIZATION_SNAPSHOT",
            "generatedAt": timezone.now().isoformat(),
            "operator": str(options["operator"]),
            "secretPolicy": {
                "containsPasswords": False,
                "containsTokens": False,
                "containsEncryptionKeys": False,
                "note": "Passwords, tokens, signing secrets and encryption keys must be provisioned through a separate secure channel.",
            },
            "runtimeSettings": {name: _json_value(getattr(settings, name, None)) for name in SAFE_SETTING_NAMES},
            "dictionaries": dictionaries,
            "roles": roles,
            "administrators": admins,
            "interfaceMappings": mappings,
            "migrations": migration_rows,
            "counts": {
                "roles": len(roles),
                "administrators": len(admins),
                "interfaceMappings": len(mappings),
                "migrations": len(migration_rows),
                "dictionaryRows": sum(len(rows) for rows in dictionaries.values()),
            },
        }
        raw = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
        output.write_bytes(raw)
        digest = hashlib.sha256(raw).hexdigest()
        sidecar = output.with_suffix(output.suffix + ".sha256")
        sidecar.write_text(f"{digest}  {output.name}\n", encoding="ascii")
        self.stdout.write(
            self.style.SUCCESS(
                f"SCHOOL_INITIALIZATION_SNAPSHOT_OK path={output} sha256={digest} roles={len(roles)} admins={len(admins)} mappings={len(mappings)}"
            )
        )
