"""Fail-closed tenant-scoped backfill of mutable HR10 rows to HR03 UUIDs.

Sealed ``HrDevelopmentFact`` history is intentionally not rewritten: its V1
content hash and append-only database seal must remain byte-for-byte verifiable.
Readers bridge those historical rows through the tenant-scoped legacy mapping.
"""
from collections import defaultdict

from django.db import migrations


_MUTABLE_MODEL_NAMES = (
    "HrDevelopmentPlan",
    "HrTrainingRequest",
    "HrLearningEnrollment",
    "HrDevelopmentNeed",
    "HrFurtherStudyCase",
    "HrEnterprisePracticeAssignment",
    "HrDevelopmentOutput",
    "HrDevelopmentMetricLedger",
    "HrDevelopmentRiskCase",
)


def _resolve_tenant_mapping(Staff, *, alias, tenant_id, legacy_ids):
    mapping = {}
    duplicates = set()
    for staff in Staff.objects.using(alias).filter(
        tenant_id=tenant_id,
        legacy_employee_id__in=legacy_ids,
    ).only("id", "legacy_employee_id"):
        key = int(staff.legacy_employee_id)
        if key in mapping and mapping[key] != staff.id:
            duplicates.add(key)
        mapping[key] = staff.id
    if duplicates:
        raise RuntimeError(
            "HR10_STAFF_UUID_BACKFILL_AMBIGUOUS:"
            f"tenant={tenant_id},legacy_ids={sorted(duplicates)[:20]}"
        )
    missing = sorted(set(legacy_ids) - set(mapping))
    if missing:
        raise RuntimeError(
            "HR10_STAFF_UUID_BACKFILL_MISSING:"
            f"tenant={tenant_id},legacy_ids={missing[:20]}"
        )
    return mapping


def _collect_required_mappings(apps, *, alias):
    required = defaultdict(set)
    for model_name in _MUTABLE_MODEL_NAMES:
        Model = apps.get_model("hr10_development", model_name)
        rows = (
            Model.objects.using(alias)
            .filter(staff_master_uuid__isnull=True)
            .exclude(staff_master_id__isnull=True)
            .values_list("tenant_id", "staff_master_id")
            .distinct()
        )
        for tenant_id, legacy_id in rows.iterator(chunk_size=2000):
            required[int(tenant_id)].add(int(legacy_id))
    return required


def backfill_mutable_staff_uuid(apps, schema_editor):
    alias = schema_editor.connection.alias
    Staff = apps.get_model("hr_staff", "HrStaffMaster")

    # Preflight all mutable rows before performing the first write. This keeps a
    # dirty tenant from producing a partially backfilled fleet of HR10 tables.
    required = _collect_required_mappings(apps, alias=alias)
    mappings = {
        tenant_id: _resolve_tenant_mapping(
            Staff,
            alias=alias,
            tenant_id=tenant_id,
            legacy_ids=legacy_ids,
        )
        for tenant_id, legacy_ids in required.items()
    }

    for model_name in _MUTABLE_MODEL_NAMES:
        Model = apps.get_model("hr10_development", model_name)
        last_pk = 0
        while True:
            rows = list(
                Model.objects.using(alias)
                .filter(pk__gt=last_pk, staff_master_uuid__isnull=True)
                .exclude(staff_master_id__isnull=True)
                .order_by("pk")[:500]
            )
            if not rows:
                break
            last_pk = rows[-1].pk
            for row in rows:
                row.staff_master_uuid = mappings[int(row.tenant_id)][int(row.staff_master_id)]
            Model.objects.using(alias).bulk_update(
                rows, ["staff_master_uuid"], batch_size=500
            )


def no_reverse_data(apps, schema_editor):
    # Canonical identity is an authority correction. Never synthesize legacy ids
    # from UUIDs during reverse migration.
    pass


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("hr10_development", "0026_canonical_hr03_staff_uuid"),
    ]

    operations = [
        migrations.RunPython(backfill_mutable_staff_uuid, no_reverse_data),
    ]
