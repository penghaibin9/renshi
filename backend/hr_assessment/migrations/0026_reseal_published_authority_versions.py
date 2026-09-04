import hashlib
import json

from django.db import migrations


VERSION_MODELS = (
    "HrAssessmentPolicyVersion",
    "HrRatingScaleVersion",
    "HrIndicatorVersion",
    "HrIndicatorSetVersion",
    "HrAssessmentWorkflowVersion",
    "HrAssessmentClassificationProfileVersion",
    "HrGateRuleVersion",
    "HrResultRuleVersion",
    "HrExcellentQuotaPolicy",
)


def _hash(row):
    excluded = {"id", "created_at", "updated_at", "content_hash", "status"}
    payload = {}
    for field in row._meta.concrete_fields:
        if field.name in excluded:
            continue
        payload[field.name] = getattr(row, field.attname)
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def reseal_versions_and_cycle_snapshots(apps, schema_editor):
    models = {
        name: apps.get_model("hr_assessment", name)
        for name in VERSION_MODELS
    }
    for Model in models.values():
        for row in Model.objects.filter(status="PUBLISHED").iterator(chunk_size=500):
            digest = _hash(row)
            if row.content_hash != digest:
                Model.objects.filter(pk=row.pk).update(content_hash=digest)

    Snapshot = apps.get_model("hr_assessment", "HrCycleSnapshot")

    def digest(model_name, tenant_id, row_id):
        if not row_id:
            return ""
        row = models[model_name].objects.filter(
            tenant_id=tenant_id,
            id=row_id,
            status="PUBLISHED",
        ).first()
        return _hash(row) if row is not None else ""

    for snapshot in Snapshot.objects.all().iterator(chunk_size=200):
        changed = []
        policy = dict(snapshot.frozen_policy_json or {})
        policy_hash = digest(
            "HrAssessmentPolicyVersion", snapshot.tenant_id, policy.get("id")
        )
        if policy_hash:
            policy["contentHash"] = policy_hash
        result_rule = dict(policy.get("resultRule") or {})
        result_hash = digest(
            "HrResultRuleVersion", snapshot.tenant_id, result_rule.get("id")
        )
        if result_hash:
            result_rule["contentHash"] = result_hash
            policy["resultRule"] = result_rule
        quota = dict(policy.get("excellentQuota") or {})
        quota_hash = digest(
            "HrExcellentQuotaPolicy", snapshot.tenant_id, quota.get("id")
        )
        if quota_hash:
            quota["contentHash"] = quota_hash
            policy["excellentQuota"] = quota
        if policy != (snapshot.frozen_policy_json or {}):
            snapshot.frozen_policy_json = policy
            changed.append("frozen_policy_json")

        for field_name, model_name in (
            ("frozen_rating_scale_json", "HrRatingScaleVersion"),
            ("frozen_indicator_set_json", "HrIndicatorSetVersion"),
            ("frozen_workflow_json", "HrAssessmentWorkflowVersion"),
        ):
            value = dict(getattr(snapshot, field_name) or {})
            value_hash = digest(model_name, snapshot.tenant_id, value.get("id"))
            if value_hash and value.get("contentHash") != value_hash:
                value["contentHash"] = value_hash
                setattr(snapshot, field_name, value)
                changed.append(field_name)
        if changed:
            snapshot.save(update_fields=changed)


class Migration(migrations.Migration):

    dependencies = [
        ("hr_assessment", "0025_hrassessmentobjection_decision_code_and_more"),
    ]

    operations = [
        migrations.RunPython(
            reseal_versions_and_cycle_snapshots,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
