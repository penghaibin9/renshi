"""Fail-closed as-of adapters for formal-fact HR authorities.

HR06 and HR12 use append-only execution/revision chains; HR07/13/14/16 use
effective formal fact rows. Historical evidence includes only chain nodes that
were effective by the requested as-of date, so later corrections/revocations do
not rewrite already frozen earlier evidence.

These adapters intentionally avoid import-time dependencies on HR13/HR14/HR16.
Before the parallel authority app is merged, Django's app registry lookup fails
and the source remains UNAVAILABLE.  After integration, the same adapter hashes
only append-only/effective formal facts.  Mutable workflow/current-projection
fields are not accepted as historical evidence.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from typing import Iterable

from django.apps import apps
from django.core.serializers.json import DjangoJSONEncoder

from hr_data.models import (
    AsOfEvidenceSnapshot,
    DimensionDefinitionVersion,
    MetricDefinitionVersion,
    PopulationDefinitionVersion,
)
from hr_data.services.source_gate import SourceStatus


@dataclass(frozen=True)
class FactSpec:
    key: str
    app_label: str
    model_name: str
    as_of_field: str
    allowed_statuses: tuple[str, ...]
    hash_fields: tuple[str, ...]


@dataclass(frozen=True)
class DomainSpec:
    domain: str
    provider_version: str
    namespaces: frozenset[str]
    field_fact_map: dict[str, str]
    facts: dict[str, FactSpec]


def _normalize_path(value: str) -> str:
    return str(value or "").strip().lower().replace("_", "")


def _predicate_fields(node) -> set[str]:
    fields: set[str] = set()
    if not isinstance(node, dict):
        return fields
    if "field" in node:
        field = str(node.get("field") or "").strip()
        if field:
            fields.add(field)
        return fields
    for key in ("and", "or"):
        children = node.get(key)
        if isinstance(children, list):
            for child in children:
                fields.update(_predicate_fields(child))
    if "not" in node:
        fields.update(_predicate_fields(node.get("not")))
    return fields


def _definition(
    *,
    tenant_id: int,
    definition_kind: str,
    definition_code: str,
    definition_version: int,
):
    if definition_kind == AsOfEvidenceSnapshot.DefinitionKind.POPULATION:
        return PopulationDefinitionVersion.objects.filter(
            tenant_id=tenant_id,
            population_code=definition_code,
            version_no=definition_version,
        ).first()
    if definition_kind == AsOfEvidenceSnapshot.DefinitionKind.DIMENSION:
        return DimensionDefinitionVersion.objects.filter(
            tenant_id=tenant_id,
            dimension_code=definition_code,
            version_no=definition_version,
        ).first()
    if definition_kind == AsOfEvidenceSnapshot.DefinitionKind.METRIC:
        return MetricDefinitionVersion.objects.filter(
            tenant_id=tenant_id,
            metric_code=definition_code,
            version_no=definition_version,
        ).first()
    return None


def _population_for_metric(*, tenant_id: int, metric: MetricDefinitionVersion):
    try:
        expression = json.loads(metric.expression or "{}")
        population_version = int(expression.get("populationVersion"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return PopulationDefinitionVersion.objects.filter(
        tenant_id=tenant_id,
        population_code=metric.population_code,
        version_no=population_version,
    ).first()


def _required_fields(*, tenant_id: int, definition_kind: str, definition):
    fields: set[str] = set()
    root_domain = ""
    if definition_kind == AsOfEvidenceSnapshot.DefinitionKind.POPULATION:
        root_domain = str(definition.root_domain or "").upper()
        fields.update(_predicate_fields(definition.predicate_json))
    elif definition_kind == AsOfEvidenceSnapshot.DefinitionKind.DIMENSION:
        fields.add(str(definition.attribute_path or ""))
        root_domain = str(definition.source_domain or "").upper()
    elif definition_kind == AsOfEvidenceSnapshot.DefinitionKind.METRIC:
        population = _population_for_metric(tenant_id=tenant_id, metric=definition)
        if population is None:
            return {"__invalid_population__"}, ""
        root_domain = str(population.root_domain or "").upper()
        fields.update(_predicate_fields(population.predicate_json))
        try:
            expression = json.loads(definition.expression or "{}")
        except (TypeError, json.JSONDecodeError):
            return {"__invalid_expression__"}, root_domain
        metric_field = str(expression.get("field") or "").strip()
        if metric_field:
            fields.add(metric_field)
    return fields, root_domain


def _source_domains(definition_kind: str, definition) -> set[str]:
    if definition_kind == AsOfEvidenceSnapshot.DefinitionKind.DIMENSION:
        return {str(definition.source_domain or "").upper()}
    return {str(item or "").upper() for item in (definition.source_domains or [])}


def _fact_keys(
    *,
    spec: DomainSpec,
    fields: Iterable[str],
    root_domain: str,
    only_source: bool,
):
    normalized = {_normalize_path(field) for field in fields if str(field or "").strip()}
    fact_keys: set[str] = set()
    unsupported: set[str] = set()
    for field in normalized:
        namespace = field.split(".", 1)[0]
        if namespace in spec.namespaces:
            fact_key = spec.field_fact_map.get(field)
            if fact_key is None:
                unsupported.add(field)
            else:
                fact_keys.add(fact_key)
        elif only_source:
            unsupported.add(field)
    if root_domain == spec.domain and not fact_keys and not unsupported:
        unsupported.add(f"{spec.domain.lower()}-root-without-formal-fact-field")
    return fact_keys, unsupported


def _model(spec: FactSpec):
    try:
        return apps.get_model(spec.app_label, spec.model_name)
    except LookupError:
        return None


def _hash_facts(
    *,
    tenant_id: int,
    as_of_date: date,
    domain_spec: DomainSpec,
    fact_keys: set[str],
):
    digest = hashlib.sha256()
    digest.update(
        json.dumps(
            {
                "providerVersion": domain_spec.provider_version,
                "tenantId": tenant_id,
                "asOfDate": as_of_date.isoformat(),
                "factKinds": sorted(fact_keys),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    digest.update(b"\n")

    for key in sorted(fact_keys):
        fact_spec = domain_spec.facts[key]
        model = _model(fact_spec)
        if model is None:
            return None
        queryset = model.objects.filter(
            tenant_id=tenant_id,
            **{f"{fact_spec.as_of_field}__lte": as_of_date},
        )
        if fact_spec.allowed_statuses:
            queryset = queryset.filter(status__in=fact_spec.allowed_statuses)
        rows = (
            queryset.order_by("id")
            .values_list(*fact_spec.hash_fields)
            .iterator(chunk_size=2000)
        )
        for row in rows:
            digest.update(key.encode("ascii"))
            digest.update(b":")
            digest.update(
                json.dumps(
                    row,
                    cls=DjangoJSONEncoder,
                    separators=(",", ":"),
                    ensure_ascii=False,
                ).encode("utf-8")
            )
            digest.update(b"\n")
    return digest.hexdigest()



def _digest_rows(digest, label: str, rows):
    for row in rows:
        digest.update(label.encode("ascii"))
        digest.update(b":")
        digest.update(
            json.dumps(
                row,
                cls=DjangoJSONEncoder,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        )
        digest.update(b"\n")


def _chain_digest(*, provider_version: str, tenant_id: int, as_of_date: date, fact_kinds):
    digest = hashlib.sha256()
    digest.update(
        json.dumps(
            {
                "providerVersion": provider_version,
                "tenantId": tenant_id,
                "asOfDate": as_of_date.isoformat(),
                "factKinds": list(fact_kinds),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    digest.update(b"\n")
    return digest


def _hash_hr06_chain(*, tenant_id: int, as_of_date: date, domain_spec: DomainSpec):
    snapshot_model = _model(domain_spec.facts["change"])
    try:
        receipt_model = apps.get_model("hr_changes", "HrChangeAuthorityReceipt")
    except LookupError:
        receipt_model = None
    if snapshot_model is None or receipt_model is None:
        return None

    digest = _chain_digest(
        provider_version=domain_spec.provider_version,
        tenant_id=tenant_id,
        as_of_date=as_of_date,
        fact_kinds=("execution", "authority_receipt"),
    )
    snapshots = (
        snapshot_model.objects.filter(
            tenant_id=tenant_id,
            effective_at__lte=as_of_date,
            change_case_id__tenant_id=tenant_id,
            change_case_id__staff_master_id__tenant_id=tenant_id,
        )
        .order_by("id")
        .values_list(
            "id",
            "change_case_id",
            "change_case_id__staff_master_id",
            "change_case_id__action_id__code",
            "change_case_id__reason_id__code",
            "change_case_id__source_org_id_id",
            "change_case_id__target_org_id_id",
            "change_case_id__source_position_id_id",
            "change_case_id__target_position_id_id",
            "effective_at",
            "applied_at",
            "case_version",
            "provider_code",
            "provider_receipt_hash",
            "content_hash",
        )
        .iterator(chunk_size=2000)
    )
    _digest_rows(digest, "execution", snapshots)
    receipts = (
        receipt_model.objects.filter(
            tenant_id=tenant_id,
            effective_at__date__lte=as_of_date,
        )
        .order_by("change_case_id", "sequence_no", "id")
        .values_list(
            "id",
            "change_case_id",
            "effective_snapshot_id",
            "sequence_no",
            "kind",
            "authority_effect",
            "provider_code",
            "provider_case_id",
            "provider_case_version",
            "provider_snapshot_hash",
            "source_record_id",
            "idempotency_key",
            "payload_json",
            "effective_at",
            "content_hash",
        )
        .iterator(chunk_size=2000)
    )
    _digest_rows(digest, "authority_receipt", receipts)
    return digest.hexdigest()


def _hash_hr12_chain(*, tenant_id: int, as_of_date: date, domain_spec: DomainSpec):
    result_model = _model(domain_spec.facts["assessment"])
    try:
        revision_model = apps.get_model("hr_assessment", "HrResultRevision")
        case_model = apps.get_model("hr_assessment", "HrAssessmentCase")
    except LookupError:
        revision_model = case_model = None
    if result_model is None or revision_model is None or case_model is None:
        return None

    digest = _chain_digest(
        provider_version=domain_spec.provider_version,
        tenant_id=tenant_id,
        as_of_date=as_of_date,
        fact_kinds=("result", "revision", "case_identity"),
    )
    result_rows = list(
        result_model.objects.filter(
            tenant_id=tenant_id,
            finalized_at__date__lte=as_of_date,
        )
        .order_by("id")
        .values_list(
            "id",
            "case_id",
            "assessment_type",
            "cycle_id",
            "grade_code",
            "display_grade_snapshot_json",
            "calculated_score",
            "decision_reason",
            "policy_version_id",
            "decision_session_id",
            "finalized_at",
            "result_version_no",
            "status",
            "calculation_hash",
            "content_hash",
            "sealed_at",
        )
    )
    _digest_rows(digest, "result", result_rows)
    result_ids = [row[0] for row in result_rows]
    case_ids = [row[1] for row in result_rows]
    revisions = (
        revision_model.objects.filter(
            tenant_id=tenant_id,
            result_id__in=result_ids,
            effective_at__date__lte=as_of_date,
        )
        .order_by("result_id", "new_version", "effective_at", "id")
        .values_list(
            "id",
            "result_id",
            "correction_no",
            "previous_version",
            "new_version",
            "revision_type",
            "reason",
            "authority_staff_id",
            "before_snapshot_json",
            "after_snapshot_json",
            "effective_at",
            "content_hash",
            "sealed_at",
        )
        .iterator(chunk_size=2000)
    )
    _digest_rows(digest, "revision", revisions)
    cases = (
        case_model.objects.filter(tenant_id=tenant_id, id__in=case_ids)
        .order_by("id")
        .values_list("id", "staff_id", "assessment_type", "cycle_id")
        .iterator(chunk_size=2000)
    )
    _digest_rows(digest, "case_identity", cases)
    return digest.hexdigest()

def _hash_hr04_chain(*, tenant_id: int, as_of_date: date, domain_spec: DomainSpec):
    fact_model = _model(domain_spec.facts["hiring"])
    try:
        revision_model = apps.get_model("hr_recruitment", "HrHiringDecisionRevision")
    except LookupError:
        revision_model = None
    if fact_model is None or revision_model is None:
        return None
    digest = _chain_digest(
        provider_version=domain_spec.provider_version, tenant_id=tenant_id,
        as_of_date=as_of_date, fact_kinds=("hiring_fact", "hiring_revision"),
    )
    facts = list(
        fact_model.objects.filter(tenant_id=tenant_id, accepted_at__date__lte=as_of_date)
        .order_by("id")
        .values_list(
            "id", "offer_id", "proposed_hire_id", "application_id", "candidate_id",
            "recruitment_position_id", "offer_no", "rank", "final_score",
            "employment_type", "expected_report_date", "accepted_at", "approved_at",
            "approved_by", "content_hash", "sealed_at",
        )
    )
    _digest_rows(digest, "hiring_fact", facts)
    fact_ids = [row[0] for row in facts]
    revisions = (
        revision_model.objects.filter(
            tenant_id=tenant_id, fact_id__in=fact_ids, effective_at__date__lte=as_of_date
        )
        .order_by("fact_id", "new_version", "effective_at", "id")
        .values_list(
            "id", "fact_id", "correction_no", "previous_version", "new_version",
            "revision_type", "before_snapshot_json", "after_snapshot_json",
            "effective_at", "content_hash", "sealed_at",
        ).iterator(chunk_size=2000)
    )
    _digest_rows(digest, "hiring_revision", revisions)
    return digest.hexdigest()


def _hash_hr05_chain(*, tenant_id: int, as_of_date: date, domain_spec: DomainSpec):
    snapshot_model = _model(domain_spec.facts["activation"])
    try:
        amendment_model = apps.get_model("hr_onboarding", "HrOnboardingActivationAmendment")
        case_model = apps.get_model("hr_onboarding", "HrOnboardingCase")
        handoff_model = apps.get_model("hr_recruitment", "HrRecruitmentHandoff")
    except LookupError:
        amendment_model = case_model = handoff_model = None
    if snapshot_model is None or amendment_model is None or case_model is None:
        return None
    digest = _chain_digest(
        provider_version=domain_spec.provider_version, tenant_id=tenant_id,
        as_of_date=as_of_date, fact_kinds=("activation_snapshot", "activation_amendment", "case_identity", "hr04_handoff"),
    )
    snapshots = list(
        snapshot_model.objects.filter(tenant_id=tenant_id, activated_at__date__lte=as_of_date)
        .order_by("id")
        .values_list(
            "id", "case_id", "activated_at", "person_id", "staff_master_id",
            "employment_id", "assignment_id", "staff_no", "organization_id",
            "position_id", "source_type", "source_id", "hr04_proposed_hire_id",
            "hr04_application_id", "source_versions_json", "content_hash", "sealed_at",
        )
    )
    _digest_rows(digest, "activation_snapshot", snapshots)
    snapshot_ids = [row[0] for row in snapshots]
    case_ids = [row[1] for row in snapshots]
    amendments = (
        amendment_model.objects.filter(
            tenant_id=tenant_id, snapshot_id__in=snapshot_ids, effective_at__date__lte=as_of_date
        )
        .order_by("snapshot_id", "sequence_no", "effective_at", "id")
        .values_list(
            "id", "snapshot_id", "predecessor_id", "sequence_no", "action",
            "before_snapshot_json", "after_snapshot_json", "effective_at",
            "content_hash", "sealed_at",
        ).iterator(chunk_size=2000)
    )
    _digest_rows(digest, "activation_amendment", amendments)
    cases = list(
        case_model.objects.filter(tenant_id=tenant_id, id__in=case_ids).order_by("id").values_list(
            "id", "source_type", "source_id", "hr04_proposed_hire_id", "hr04_application_id",
            "hr03_person_id", "hr03_staff_master_id", "hr03_employment_id", "hr03_assignment_id",
        )
    )
    _digest_rows(digest, "case_identity", cases)
    if handoff_model is not None:
        proposed_ids = [str(row[12]) for row in snapshots if row[10] == "HR04_HIRE" and row[12]]
        handoffs = handoff_model.objects.filter(tenant_id=tenant_id, proposed_hire_id__in=proposed_ids).order_by("id").values_list(
            "id", "proposed_hire_id", "application_id", "status", "handoff_at", "hr05_case_id", "payload_snapshot"
        ).iterator(chunk_size=2000)
        _digest_rows(digest, "hr04_handoff", handoffs)
    return digest.hexdigest()


def _hash_hr15_chain(*, tenant_id: int, as_of_date: date, domain_spec: DomainSpec):
    result_model = _model(domain_spec.facts["payroll"])
    try:
        period_model = apps.get_model("hr_payroll", "PayrollPeriod")
    except LookupError:
        period_model = None
    if result_model is None or period_model is None:
        return None
    digest = _chain_digest(
        provider_version=domain_spec.provider_version, tenant_id=tenant_id,
        as_of_date=as_of_date, fact_kinds=("payroll_result", "payroll_period"),
    )
    results = list(
        result_model.objects.filter(
            tenant_id=tenant_id, status__in=("FINALIZED", "ADJUSTED", "REVERSED"),
            effective_at__date__lte=as_of_date,
        ).order_by("effective_at", "id").values_list(
            "id", "result_no", "payroll_period_id", "staff_id", "currency_code",
            "gross_amount", "deduction_amount", "net_amount", "status",
            "supersedes_result_id", "authority_reason", "authority_evidence_ref",
            "authority_actor_id", "effective_at", "content_hash", "sealed_at",
        )
    )
    _digest_rows(digest, "payroll_result", results)
    period_ids = [row[2] for row in results]
    periods = (
        period_model.objects.filter(tenant_id=tenant_id, id__in=period_ids).order_by("id")
        .values_list("id", "period_code", "start_date", "end_date", "finalized_at", "time_source_snapshot_json")
        .iterator(chunk_size=2000)
    )
    _digest_rows(digest, "payroll_period", periods)
    return digest.hexdigest()


def _provider(
    *,
    spec: DomainSpec,
    tenant_id: int,
    source_domain: str,
    definition_kind: str,
    definition_code: str,
    definition_version: int,
    as_of_date: date,
):
    if int(tenant_id or 0) <= 0 or str(source_domain or "").upper() != spec.domain:
        return {"status": SourceStatus.ERROR.value}
    if not isinstance(as_of_date, date):
        return {"status": SourceStatus.ERROR.value}
    definition_kind = str(definition_kind or "").upper()
    try:
        definition_version = int(definition_version)
    except (TypeError, ValueError):
        return {"status": SourceStatus.ERROR.value}
    definition = _definition(
        tenant_id=int(tenant_id),
        definition_kind=definition_kind,
        definition_code=str(definition_code or "").upper(),
        definition_version=definition_version,
    )
    if definition is None:
        return {"status": SourceStatus.ERROR.value}
    fields, root_domain = _required_fields(
        tenant_id=int(tenant_id),
        definition_kind=definition_kind,
        definition=definition,
    )
    if "__invalid_population__" in fields or "__invalid_expression__" in fields:
        return {"status": SourceStatus.ERROR.value}
    domains = _source_domains(definition_kind, definition)
    fact_keys, unsupported = _fact_keys(
        spec=spec,
        fields=fields,
        root_domain=root_domain,
        only_source=domains == {spec.domain},
    )
    if unsupported or not fact_keys:
        return {
            "status": SourceStatus.UNAVAILABLE.value,
            "sourceVersion": spec.provider_version,
            "evidenceHash": "",
        }
    if spec.domain in {"HR06", "HR12"}:
        from hr_data.providers.chain_fact_quality import quality_provider

        quality_rule = {
            "HR06": "HR06_CHANGE_CHAIN_INTEGRITY",
            "HR12": "HR12_RESULT_REVISION_CHAIN_INTEGRITY",
        }[spec.domain]
        quality = quality_provider(
            tenant_id=int(tenant_id),
            source_domain=spec.domain,
            rule_code=quality_rule,
            rule_version=1,
            rule_parameters={},
            as_of_date=as_of_date,
            actor_user_id=None,
        )
        quality_status = str((quality or {}).get("status") or "").upper()
        if quality_status == SourceStatus.UNAVAILABLE.value:
            return {
                "status": SourceStatus.UNAVAILABLE.value,
                "sourceVersion": spec.provider_version,
                "evidenceHash": "",
            }
        if quality_status != SourceStatus.OK.value or (quality or {}).get("findings"):
            return {
                "status": SourceStatus.ERROR.value,
                "sourceVersion": spec.provider_version,
                "evidenceHash": "",
            }
    if spec.domain in {"HR04", "HR05", "HR15"}:
        from hr_data.providers.round6_chain_quality import quality_provider

        quality_rule = {
            "HR04": "HR04_HIRING_REVISION_CHAIN_INTEGRITY",
            "HR05": "HR05_ACTIVATION_AMENDMENT_CHAIN_INTEGRITY",
            "HR15": "HR15_PAYROLL_RESULT_CHAIN_INTEGRITY",
        }[spec.domain]
        quality = quality_provider(
            tenant_id=int(tenant_id), source_domain=spec.domain, rule_code=quality_rule,
            rule_version=1, rule_parameters={}, as_of_date=as_of_date, actor_user_id=None,
        )
        quality_status = str((quality or {}).get("status") or "").upper()
        if quality_status == SourceStatus.UNAVAILABLE.value:
            return {"status": SourceStatus.UNAVAILABLE.value, "sourceVersion": spec.provider_version, "evidenceHash": ""}
        if quality_status != SourceStatus.OK.value or (quality or {}).get("findings"):
            return {"status": SourceStatus.ERROR.value, "sourceVersion": spec.provider_version, "evidenceHash": ""}

    if spec.domain == "HR04":
        evidence_hash = _hash_hr04_chain(tenant_id=int(tenant_id), as_of_date=as_of_date, domain_spec=spec)
    elif spec.domain == "HR05":
        evidence_hash = _hash_hr05_chain(tenant_id=int(tenant_id), as_of_date=as_of_date, domain_spec=spec)
    elif spec.domain == "HR15":
        evidence_hash = _hash_hr15_chain(tenant_id=int(tenant_id), as_of_date=as_of_date, domain_spec=spec)
    elif spec.domain == "HR06":
        evidence_hash = _hash_hr06_chain(
            tenant_id=int(tenant_id), as_of_date=as_of_date, domain_spec=spec
        )
    elif spec.domain == "HR12":
        evidence_hash = _hash_hr12_chain(
            tenant_id=int(tenant_id), as_of_date=as_of_date, domain_spec=spec
        )
    else:
        evidence_hash = _hash_facts(
            tenant_id=int(tenant_id),
            as_of_date=as_of_date,
            domain_spec=spec,
            fact_keys=fact_keys,
        )
    if evidence_hash is None:
        return {
            "status": SourceStatus.UNAVAILABLE.value,
            "sourceVersion": spec.provider_version,
            "evidenceHash": "",
        }
    return {
        "status": SourceStatus.OK.value,
        "sourceVersion": spec.provider_version,
        "evidenceHash": evidence_hash,
    }



HR04_SPEC = DomainSpec(
    domain="HR04", provider_version="hr04-hiring-revision-chain-v1",
    namespaces=frozenset({"hiring"}),
    field_fact_map={_normalize_path(field): "hiring" for field in (
        "hiring.candidateId", "hiring.recruitmentPositionId", "hiring.offerNo",
        "hiring.rank", "hiring.finalScore", "hiring.employmentType",
        "hiring.expectedReportDate", "hiring.acceptedAt", "hiring.status",
    )},
    facts={"hiring": FactSpec(
        key="hiring", app_label="hr_recruitment", model_name="HrHiringDecisionFact",
        as_of_field="accepted_at", allowed_statuses=(),
        hash_fields=("id", "candidate_id", "accepted_at", "content_hash", "sealed_at"),
    )},
)

HR05_SPEC = DomainSpec(
    domain="HR05", provider_version="hr05-activation-amendment-chain-v1",
    namespaces=frozenset({"onboarding", "activation"}),
    field_fact_map={_normalize_path(field): "activation" for field in (
        "onboarding.personId", "onboarding.staffMasterId", "onboarding.employmentId",
        "onboarding.assignmentId", "onboarding.staffNo", "onboarding.organizationId",
        "onboarding.positionId", "onboarding.sourceType", "onboarding.sourceId",
        "onboarding.activatedAt", "onboarding.status",
        "activation.personId", "activation.staffMasterId", "activation.staffNo", "activation.status",
    )},
    facts={"activation": FactSpec(
        key="activation", app_label="hr_onboarding", model_name="HrOnboardingActivationSnapshot",
        as_of_field="activated_at", allowed_statuses=(),
        hash_fields=("id", "case_id", "activated_at", "staff_master_id", "content_hash", "sealed_at"),
    )},
)

HR15_SPEC = DomainSpec(
    domain="HR15", provider_version="hr15-payroll-result-chain-v1",
    namespaces=frozenset({"payroll"}),
    field_fact_map={_normalize_path(field): "payroll" for field in (
        "payroll.resultId", "payroll.periodId", "payroll.periodCode", "payroll.staffId",
        "payroll.currencyCode", "payroll.grossAmount", "payroll.deductionAmount",
        "payroll.netAmount", "payroll.status", "payroll.effectiveAt",
    )},
    facts={"payroll": FactSpec(
        key="payroll", app_label="hr_payroll", model_name="PayrollResultFact",
        as_of_field="effective_at", allowed_statuses=("FINALIZED", "ADJUSTED", "REVERSED"),
        hash_fields=("id", "payroll_period_id", "staff_id", "status", "supersedes_result_id",
                     "authority_reason", "authority_evidence_ref", "authority_actor_id",
                     "effective_at", "content_hash", "sealed_at"),
    )},
)

HR06_SPEC = DomainSpec(
    domain="HR06",
    provider_version="hr06-change-chain-v1",
    namespaces=frozenset({"change"}),
    field_fact_map={
        _normalize_path(field): "change"
        for field in (
            "change.staffId",
            "change.actionCode",
            "change.reasonCode",
            "change.sourceOrgId",
            "change.targetOrgId",
            "change.sourcePositionId",
            "change.targetPositionId",
            "change.effectiveDate",
        )
    },
    facts={
        "change": FactSpec(
            key="change",
            app_label="hr_changes",
            model_name="HrChangeEffectiveSnapshot",
            as_of_field="effective_at",
            allowed_statuses=(),
            hash_fields=("id", "change_case_id", "effective_at", "content_hash"),
        )
    },
)

HR07_SPEC = DomainSpec(
    domain="HR07",
    provider_version="hr07-contract-facts-v1",
    namespaces=frozenset({"contract"}),
    field_fact_map={
        _normalize_path(field): "contract"
        for field in (
            "contract.staffId",
            "contract.employmentRelationshipId",
            "contract.agreementType",
            "contract.subjectType",
            "contract.versionType",
            "contract.effectiveFrom",
            "contract.effectiveTo",
            "contract.status",
        )
    },
    facts={
        "contract": FactSpec(
            key="contract",
            app_label="hr_contracts",
            model_name="HrContractVersion",
            as_of_field="effective_from",
            allowed_statuses=("EFFECTIVE", "SUPERSEDED", "TERMINATED", "EXPIRED", "VOID"),
            hash_fields=(
                "id",
                "agreement_id",
                "agreement__staff_id",
                "agreement__employment_relationship_id",
                "agreement__subject_type",
                "agreement__agreement_no",
                "agreement__agreement_type",
                "version_no",
                "version_type",
                "effective_from",
                "effective_to",
                "status",
                "supersedes_version_id",
                "content_hash",
            ),
        )
    },
)


HR12_SPEC = DomainSpec(
    domain="HR12",
    provider_version="hr12-result-chain-v1",
    namespaces=frozenset({"assessment"}),
    field_fact_map={
        _normalize_path(field): "assessment"
        for field in (
            "assessment.resultId",
            "assessment.staffId",
            "assessment.assessmentType",
            "assessment.cycleId",
            "assessment.gradeCode",
            "assessment.status",
            "assessment.finalizedAt",
        )
    },
    facts={
        "assessment": FactSpec(
            key="assessment",
            app_label="hr_assessment",
            model_name="HrFinalAssessmentResult",
            as_of_field="finalized_at",
            allowed_statuses=(),
            hash_fields=("id", "case_id", "finalized_at", "content_hash"),
        )
    },
)

HR13_SPEC = DomainSpec(
    domain="HR13",
    provider_version="hr13-title-facts-v1",
    namespaces=frozenset({"title", "professionaltitle"}),
    field_fact_map={
        _normalize_path(field): "title"
        for field in (
            "title.personId",
            "title.titleCode",
            "title.titleName",
            "title.titleSeriesCode",
            "title.titleLevelCode",
            "title.effectiveFrom",
            "title.effectiveTo",
            "title.status",
            "professionalTitle.personId",
            "professionalTitle.titleCode",
            "professionalTitle.titleName",
            "professionalTitle.titleSeriesCode",
            "professionalTitle.titleLevelCode",
            "professionalTitle.effectiveFrom",
            "professionalTitle.effectiveTo",
            "professionalTitle.status",
        )
    },
    facts={
        "title": FactSpec(
            key="title",
            app_label="hr_title",
            model_name="ProfessionalTitleResult",
            as_of_field="effective_from",
            allowed_statuses=("EFFECTIVE", "REVISED", "REVOKED"),
            hash_fields=(
                "id",
                "result_no",
                "person_id",
                "application_case_id",
                "title_code",
                "title_name",
                "title_series_code",
                "title_level_code",
                "effective_from",
                "effective_to",
                "status",
                "supersedes_result_id",
            ),
        )
    },
)


HR14_SPEC = DomainSpec(
    domain="HR14",
    provider_version="hr14-appointment-facts-v1",
    namespaces=frozenset({"appointment"}),
    field_fact_map={
        _normalize_path(field): "appointment"
        for field in (
            "appointment.personId",
            "appointment.positionInstanceId",
            "appointment.levelCode",
            "appointment.effectiveFrom",
            "appointment.effectiveTo",
            "appointment.status",
        )
    },
    facts={
        "appointment": FactSpec(
            key="appointment",
            app_label="hr_appointment",
            model_name="PositionAppointmentFact",
            as_of_field="effective_from",
            allowed_statuses=("EFFECTIVE", "REVISED", "ENDED", "REVOKED"),
            hash_fields=(
                "id",
                "appointment_no",
                "person_id",
                "position_instance_id",
                "application_case_id",
                "level_code",
                "effective_from",
                "effective_to",
                "status",
                "supersedes_fact_id",
            ),
        )
    },
)


HR16_SPEC = DomainSpec(
    domain="HR16",
    provider_version="hr16-exit-retirement-facts-v2",
    namespaces=frozenset({"exit", "retirement"}),
    field_fact_map={
        **{
            _normalize_path(field): "exit"
            for field in (
                "exit.personId",
                "exit.employmentRelationshipId",
                "exit.exitType",
                "exit.employmentEndDate",
                "exit.lastWorkingDate",
                "exit.accessEndAt",
            )
        },
        **{
            _normalize_path(field): "retirement"
            for field in (
                "retirement.personId",
                "retirement.retirementType",
                "retirement.statutoryDate",
                "retirement.effectiveDate",
            )
        },
    },
    facts={
        "exit": FactSpec(
            key="exit",
            app_label="hr_exit",
            model_name="ExitFact",
            as_of_field="employment_end_date",
            allowed_statuses=("EFFECTIVE", "REVISED", "REVOKED"),
            hash_fields=(
                "id",
                "fact_no",
                "person_id",
                "employment_relationship_id",
                "source_case_id",
                "exit_type",
                "employment_end_date",
                "last_working_date",
                "access_end_at",
                "supersedes_fact_id",
                "status",
                "content_hash",
                "sealed_at",
            ),
        ),
        "retirement": FactSpec(
            key="retirement",
            app_label="hr_exit",
            model_name="RetirementFact",
            as_of_field="effective_date",
            allowed_statuses=("EFFECTIVE", "REVISED", "REVOKED"),
            hash_fields=(
                "id",
                "fact_no",
                "person_id",
                "exit_fact_id",
                "retirement_type",
                "statutory_date",
                "effective_date",
                "supersedes_fact_id",
                "status",
                "content_hash",
                "sealed_at",
            ),
        ),
    },
)



def hr04_asof_provider(**kwargs):
    kwargs.pop("actor_user_id", None)
    return _provider(spec=HR04_SPEC, **kwargs)


def hr05_asof_provider(**kwargs):
    kwargs.pop("actor_user_id", None)
    return _provider(spec=HR05_SPEC, **kwargs)


def hr15_asof_provider(**kwargs):
    kwargs.pop("actor_user_id", None)
    return _provider(spec=HR15_SPEC, **kwargs)


def hr06_asof_provider(**kwargs):
    kwargs.pop("actor_user_id", None)
    return _provider(spec=HR06_SPEC, **kwargs)


def hr07_asof_provider(**kwargs):
    kwargs.pop("actor_user_id", None)
    return _provider(spec=HR07_SPEC, **kwargs)



def hr12_asof_provider(**kwargs):
    kwargs.pop("actor_user_id", None)
    return _provider(spec=HR12_SPEC, **kwargs)


def hr13_asof_provider(**kwargs):
    kwargs.pop("actor_user_id", None)
    return _provider(spec=HR13_SPEC, **kwargs)


def hr14_asof_provider(**kwargs):
    kwargs.pop("actor_user_id", None)
    return _provider(spec=HR14_SPEC, **kwargs)


def hr16_asof_provider(**kwargs):
    kwargs.pop("actor_user_id", None)
    return _provider(spec=HR16_SPEC, **kwargs)
