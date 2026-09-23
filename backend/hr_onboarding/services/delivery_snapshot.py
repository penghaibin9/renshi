"""Read-only keyed content proof for a single school's first-delivery scope.

This compares business rows after an independent restore, not merely counts.
It is NOT a backup, a customer signature, an external-system delivery receipt,
or a proof of every application table. HMAC keys stay outside output packages.
"""
from __future__ import annotations
import hashlib
import hmac
import json
import re
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

MODEL_LABELS = (
    "hr_staff.HrPerson", "hr_staff.HrStaffMaster", "hr_staff.HrEmploymentRelationship",
    "hr_staff.HrStaffAssignment", "hr_staff.HrImportJob", "hr_staff.HrImportRow",
    "hr_staff.HrImportIssue", "hr_staff.HrStaffAuditEvent", "hr_structure.HrOrganization",
    "hr_structure.HrOrganizationVersion", "hr_structure.HrPosition", "hr_structure.HrPositionReservation",
    "hr_onboarding.HrOnboardingCase", "hr_onboarding.HrOnboardingTemplate",
    "hr_onboarding.HrOnboardingTemplateVersion", "hr_onboarding.HrOnboardingTaskDefinition",
    "hr_onboarding.HrOnboardingTaskInstance", "hr_onboarding.HrOnboardingMaterialRequirement",
    "hr_onboarding.HrOnboardingMaterial", "hr_onboarding.HrOnboardingActivationSnapshot",
    "hr_onboarding.HrOnboardingAuditEvent", "hr_onboarding.HrOnboardingIdempotencyRecord",
    "hr_onboarding.HrOnboardingOutboxEvent",
)
SCHEMA = "yueke.delivery-content-proof.2"
SCOPE = "FIRST_CUSTOMER_PERSONNEL_AND_ONBOARDING_ROWS_ONLY"
_HEX256 = re.compile(r"[0-9a-f]{64}\Z")


def _default(value):
    if isinstance(value, (Decimal, UUID)): return str(value)
    if hasattr(value, "isoformat"): return value.isoformat()
    if isinstance(value, bytes): return {"bytes_hex": value.hex()}
    raise TypeError("Unsupported snapshot value type")


def canonical(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"),
        default=_default,allow_nan=False).encode("utf-8")


def key_id(key):
    if not isinstance(key,bytes) or len(key)<32: raise ValueError("Snapshot key must have at least 32 bytes")
    return hmac.new(key,b"yueke-delivery-key-id-v1",hashlib.sha256).hexdigest()


def fingerprint_rows(rows, key, *, domain):
    key_id(key)
    digest=hmac.new(key,b"yueke.delivery.rows.1/"+domain.encode(),hashlib.sha256)
    count=0
    for row in rows:
        data=canonical(row)
        digest.update(len(data).to_bytes(8,"big"));digest.update(data);count+=1
    return {"rows":count,"content_hmac_sha256":digest.hexdigest()}


def capture_models(tenant_id, key, *, database="default"):
    from django.apps import apps
    proofs={}
    for label in MODEL_LABELS:
        model=apps.get_model(label)
        if model is None: raise ValueError("Required first-delivery model is unavailable")
        model._meta.get_field("tenant_id")
        fields=[x.attname for x in model._meta.concrete_fields]
        shape=[{"name": x.attname, "type": x.get_internal_type(), "null": x.null,
            "primary_key": x.primary_key, "unique": x.unique, "column": x.column,
            "max_length": x.max_length, "max_digits": getattr(x,"max_digits",None),
            "decimal_places": getattr(x,"decimal_places",None),
            "db_collation": getattr(x,"db_collation",None)} for x in model._meta.concrete_fields]
        rows=model._base_manager.using(database).filter(tenant_id=tenant_id).order_by(model._meta.pk.attname).values(*fields).iterator(chunk_size=500)
        proofs[label]={**fingerprint_rows(rows,key,domain=f"{tenant_id}/{label}"),
            "shape_sha256":hashlib.sha256(canonical(shape)).hexdigest()}
    return {"schema":SCHEMA,"school_id":str(tenant_id),"key_id":key_id(key),
        "captured_at":datetime.now(timezone.utc).isoformat(),"models":proofs,
        "scope":SCOPE,
        "not_proven":["private-file bytes", "all other modules", "external receipts", "customer acceptance"]}


def _digest(value):
    return isinstance(value, str) and bool(_HEX256.fullmatch(value))


def _metadata_issues(proof, prefix):
    if not isinstance(proof, dict):
        return [prefix + "_ROOT_INVALID"]
    issues = []
    school = proof.get("school_id")
    if (not isinstance(school, str) or not re.fullmatch(r"[1-9][0-9]{0,18}", school)
            or int(school) > 9223372036854775807):
        issues.append(prefix + "_SCHOOL_INVALID")
    if not _digest(proof.get("key_id")):
        issues.append(prefix + "_KEY_INVALID")
    if proof.get("scope") != SCOPE:
        issues.append(prefix + "_SCOPE_INVALID")
    try:
        stamp = proof.get("captured_at")
        if not isinstance(stamp, str) or len(stamp) > 64:
            raise ValueError("invalid timestamp")
        parsed = datetime.fromisoformat(stamp)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("timezone required")
    except (TypeError, ValueError, OverflowError):
        issues.append(prefix + "_TIMESTAMP_INVALID")
    return issues


def compare_snapshots(left, right):
    issues = _metadata_issues(left, "SOURCE") + _metadata_issues(right, "RESTORED")
    left = left if isinstance(left, dict) else {}
    right = right if isinstance(right, dict) else {}
    if left.get("schema") != SCHEMA or right.get("schema") != SCHEMA:
        issues.append("SCHEMA_MISMATCH")
    if left.get("school_id") != right.get("school_id"):
        issues.append("SCHOOL_MISMATCH")
    if not left.get("key_id") or left.get("key_id") != right.get("key_id"):
        issues.append("KEY_MISMATCH")
    a, b = left.get("models", {}), right.get("models", {})
    if not isinstance(a,dict) or not isinstance(b,dict) or set(a)!=set(MODEL_LABELS) or set(b)!=set(MODEL_LABELS):
        issues.append("MODEL_SCOPE_MISMATCH")
        a=a if isinstance(a,dict) else {}; b=b if isinstance(b,dict) else {}
    details = []
    for label in MODEL_LABELS:
        x, y = a.get(label, {}), b.get(label, {})
        okay = (isinstance(x,dict) and isinstance(y,dict) and type(x.get("rows")) is int and x["rows"]>=0
            and type(y.get("rows")) is int and x["rows"]==y["rows"]
            and _digest(x.get("shape_sha256")) and x["shape_sha256"]==y.get("shape_sha256")
            and _digest(x.get("content_hmac_sha256")) and x["content_hmac_sha256"]==y.get("content_hmac_sha256"))
        if not okay:
            issues.append("CONTENT_DIFFERENCE:" + label)
        details.append({"model": label, "equal": bool(okay)})
    return {"schema":"yueke.delivery-content-comparison.2", "status":"MATCH" if not issues else "MISMATCH",
        "issues":issues, "models":details, "release_approved":False,
        "warning":"Checksums compare supplied artifacts, not identity or truth of the collector. Keep the key and proof files restricted."}
