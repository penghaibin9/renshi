"""Bounded SQL aggregation + frozen observation receipts across university domains."""
import logging
from django.apps import apps
from django.db import DatabaseError, transaction
from django.db.models import Count
from django.utils import timezone
from hr_data.operational_catalog import CATALOG, CATALOG_VERSION, source_result
from hr_data.operational_models import OperationalSnapshot
from hr_staff.services.authority_mode_service import AuthorityModeService, AuthorityModeError
from hr_self.command_contract import CommandError, idempotency_key, command_hash
logger = logging.getLogger(__name__)

class OperationalSnapshotService:
    def __init__(self, tenant, actor):
        if not tenant or not actor:
            raise CommandError("CONTEXT_REQUIRED", "学校与操作人不能为空", 403)
        self.tenant, self.actor = int(tenant), int(actor)

    def observe(self):
        started = timezone.now().isoformat()
        items = []
        for domain, code, title, app, model_name, state_field in CATALOG:
            try:
                # Per-source savepoint allows a missing source to remain an explicit
                # error rather than poisoning the outer snapshot transaction.
                with transaction.atomic():
                    if domain == "HR03":
                        AuthorityModeService().assert_authority_available(self.tenant, require_authority=True)
                    model = apps.get_model(app, model_name)
                    fields = {f.name for f in model._meta.get_fields()}
                    if not {"tenant_id", state_field}.issubset(fields):
                        raise LookupError("SOURCE_SCHEMA_MISMATCH")
                    groups = list(model.objects.filter(tenant_id=self.tenant).order_by()
                        .values(state_field).annotate(n=Count("pk")).order_by(state_field)[:65])
                    if len(groups) > 64:
                        raise LookupError("SOURCE_STATE_CARDINALITY_LIMIT")
                    result = source_result(domain, code, title, status="OK",
                        groups=[{"state": str(x[state_field] or "UNSPECIFIED"), "count": x["n"]} for x in groups])
            except AuthorityModeError:
                result = source_result(domain, code, title, status="UNAVAILABLE", error_code="STAFF_AUTHORITY_NOT_AVAILABLE")
            except LookupError:
                result = source_result(domain, code, title, status="UNAVAILABLE", error_code="SOURCE_OR_SCHEMA_UNAVAILABLE")
            except DatabaseError:
                logger.exception("HR18 operational source failed: %s", code)
                result = source_result(domain, code, title, status="ERROR", error_code="SOURCE_QUERY_FAILED")
            result["observedAt"] = timezone.now().isoformat()
            result["authorityModel"] = app + "." + model_name
            items.append(result)
        return {"catalogVersion": CATALOG_VERSION, "scope": "CURRENT_SCHOOL", "startedAt": started,
            "finishedAt": timezone.now().isoformat(), "items": items,
            "status": "OK" if all(x["sourceStatus"] == "OK" for x in items) else "PARTIAL",
            "temporalMode": "OBSERVED_WINDOW", "atomicCrossDomainAsOf": False,
            "historicalValueCapabilities": {"HR03": "existing effective-dated evaluation",
                "HR04": "sealed hiring-decision PERSON COUNT with correction/revocation chain",
                "HR05": "sealed onboarding activation STAFF COUNT with HR04 handoff lineage",
                "HR06": "sealed personnel-change STAFF COUNT",
                "HR07": "formal contract STAFF COUNT",
                "HR12": "sealed assessment-result STAFF COUNT",
                "HR13": "title PERSON COUNT",
                "HR14": "appointment PERSON COUNT",
                "HR15": "sealed payroll-result STAFF COUNT with adjustment/reversal chain",
                "HR16": "retirement PERSON COUNT"},
            "notice": "统计对象和状态口径各不相同，不能把各模块记录数相加当作全校人数；本快照不是历史时点重建。"}

    @transaction.atomic
    def capture(self, key):
        from base.models import Company
        key = idempotency_key(key)
        if not Company.objects.select_for_update().filter(pk=self.tenant).exists():
            raise CommandError("TENANT_NOT_FOUND", "学校不存在", 404)
        digest = command_hash({"catalogVersion": CATALOG_VERSION, "actor": self.actor})
        old = OperationalSnapshot.objects.filter(tenant_id=self.tenant, idempotency_key=key).first()
        if old:
            if old.request_hash != digest:
                raise CommandError("IDEMPOTENCY_CONFLICT", "请求编号已用于其他版本或操作人", 409)
            return old, False
        item = OperationalSnapshot(tenant_id=self.tenant, idempotency_key=key, request_hash=digest,
            catalog_version=CATALOG_VERSION, payload=self.observe(), created_by=self.actor, updated_by=self.actor)
        item.evidence_hash = item.compute_hash()
        item.save()
        from hr_staff.services.audit_service import write_audit_event
        write_audit_event(tenant_id=self.tenant, action="HrDataObservationCaptured", actor_user_id=self.actor,
            business_type="HR18_OBSERVATION", business_id=str(item.id), reason=f"evidenceHash={item.evidence_hash}")
        return item, True
