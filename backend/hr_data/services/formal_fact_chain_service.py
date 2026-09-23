"""Chain-aware historical evaluation for append-only HR formal authorities.

HR06, HR12, HR13, HR14 and HR16 all preserve history by appending sealed
facts/receipts instead of rewriting the original Authority row.  Historical
HR18 values therefore resolve the authoritative chain *as of the requested
calendar date* before applying a population predicate.

The important boundary is deliberate:
- HR06 counts sealed execution snapshots and treats an orchestration rescind as
  invalidating that HR06 event only from the rescind receipt date onward;
- HR12 reconstructs the sealed final result plus corrections/revocations that
  had become effective by the requested date;
- HR13/14/16 select the terminal effective fact in each supersession chain.
"""

from __future__ import annotations

import copy
from datetime import date
from decimal import Decimal
from typing import Any

from django.apps import apps
from django.db.models import Exists, OuterRef, Prefetch, Q

from hr_data.services.evaluation_service import AsOfEvaluationError
from hr_data.services.formal_fact_evaluation_service import (
    FormalDomainSpec,
    FormalFactAsOfEvaluationService as _BaseFormalFactAsOfEvaluationService,
    _coerce,
    _compile_predicate,
    _normalize_path,
)


_SUCCESSOR_FIELDS = {
    "HR13": "supersedes_result_id",
    "HR14": "supersedes_fact_id",
    "HR16": "supersedes_fact_id",
}

# Only a durable terminal successor may retire its predecessor.  HR14 may retain
# EFFECT_PENDING successor rows after a failed provider effect; those must never
# hide the still-effective source fact.
_SUPERSEDING_STATUSES = {
    "HR13": ("EFFECTIVE", "REVISED", "REVOKED"),
    "HR14": ("EFFECTIVE", "REVISED", "ENDED", "REVOKED"),
    "HR16": ("EFFECTIVE", "REVISED", "REVOKED"),
}


def _model(app_label: str, model_name: str):
    try:
        return apps.get_model(app_label, model_name)
    except LookupError:
        return None


def _source_conflict(message: str) -> AsOfEvaluationError:
    return AsOfEvaluationError("ASOF_EVALUATION_SOURCE_CONFLICT", message)


def _assert_chain_quality(*, tenant_id: int, domain: str, as_of_date: date) -> None:
    """Fail closed when the sealed authority chain is unavailable or corrupt."""

    from hr_data.services.source_gate import SourceStatus

    if domain in {"HR06", "HR12"}:
        from hr_data.providers.chain_fact_quality import quality_provider
        rule_code = {
            "HR06": "HR06_CHANGE_CHAIN_INTEGRITY",
            "HR12": "HR12_RESULT_REVISION_CHAIN_INTEGRITY",
        }[domain]
    else:
        from hr_data.providers.round6_chain_quality import quality_provider
        rule_code = {
            "HR04": "HR04_HIRING_REVISION_CHAIN_INTEGRITY",
            "HR05": "HR05_ACTIVATION_AMENDMENT_CHAIN_INTEGRITY",
            "HR15": "HR15_PAYROLL_RESULT_CHAIN_INTEGRITY",
        }[domain]
    try:
        outcome = quality_provider(
            tenant_id=tenant_id,
            source_domain=domain,
            rule_code=rule_code,
            rule_version=1,
            rule_parameters={},
            as_of_date=as_of_date,
            actor_user_id=None,
        )
    except Exception as exc:
        raise _source_conflict(
            f"{domain} authority quality validation failed unexpectedly"
        ) from exc
    status = str(outcome.get("status") or "")
    if status == SourceStatus.UNAVAILABLE.value:
        raise AsOfEvaluationError(
            "ASOF_EVALUATION_SOURCE_UNAVAILABLE",
            f"{domain} authority quality source is unavailable",
        )
    if status != SourceStatus.OK.value:
        raise _source_conflict(f"{domain} authority quality source returned {status or 'ERROR'}")
    findings = outcome.get("findings") or []
    if findings:
        first = findings[0] if isinstance(findings[0], dict) else {}
        details = first.get("details") if isinstance(first, dict) else {}
        issue = details.get("issue") if isinstance(details, dict) else None
        raise _source_conflict(
            f"{domain} authority chain failed integrity validation"
            + (f": {issue}" if issue else "")
        )


def _matches_leaf(node: dict, spec: FormalDomainSpec, row: dict[str, Any]) -> bool:
    path = _normalize_path(node.get("field"))
    mapping = spec.field_map.get(path)
    if mapping is None:
        raise AsOfEvaluationError(
            "ASOF_EVALUATION_FIELD_UNSUPPORTED",
            f"historical {spec.domain} evaluator does not support field: {node.get('field')}",
        )
    field_name, value_type = mapping
    actual = row.get(field_name)
    op = str(node.get("op") or "").strip().lower()
    value = node.get("value")

    if op == "is_null":
        if not isinstance(value, bool):
            raise AsOfEvaluationError(
                "ASOF_EVALUATION_VALUE_INVALID", "is_null requires a boolean value"
            )
        return (actual is None) is value

    if op in {"in", "not_in"}:
        if not isinstance(value, list):
            raise AsOfEvaluationError(
                "ASOF_EVALUATION_VALUE_INVALID", f"{op} requires a list value"
            )
        expected = [_coerce(item, value_type) for item in value]
        if actual is None:
            return False
        return (actual not in expected) if op == "not_in" else (actual in expected)

    expected = _coerce(value, value_type)
    if op == "eq":
        return actual == expected
    if op == "ne":
        return actual is not None and actual != expected
    if actual is None:
        return False
    if op == "gte":
        return actual >= expected
    if op == "gt":
        return actual > expected
    if op == "lte":
        return actual <= expected
    if op == "lt":
        return actual < expected
    raise AsOfEvaluationError(
        "ASOF_EVALUATION_OPERATOR_UNSUPPORTED", f"unsupported operator: {op}"
    )


def _matches_predicate(node, spec: FormalDomainSpec, row: dict[str, Any]) -> bool:
    if not isinstance(node, dict) or not node:
        raise AsOfEvaluationError(
            "ASOF_EVALUATION_PREDICATE_INVALID", "population predicate is invalid"
        )
    keys = set(node)
    if keys == {"field", "op", "value"}:
        return _matches_leaf(node, spec, row)
    if keys == {"and"}:
        children = node["and"]
        if not isinstance(children, list) or not children:
            raise AsOfEvaluationError(
                "ASOF_EVALUATION_PREDICATE_INVALID", "and requires a non-empty list"
            )
        return all(_matches_predicate(child, spec, row) for child in children)
    if keys == {"or"}:
        children = node["or"]
        if not isinstance(children, list) or not children:
            raise AsOfEvaluationError(
                "ASOF_EVALUATION_PREDICATE_INVALID", "or requires a non-empty list"
            )
        return any(_matches_predicate(child, spec, row) for child in children)
    if keys == {"not"}:
        return not _matches_predicate(node["not"], spec, row)
    raise AsOfEvaluationError(
        "ASOF_EVALUATION_PREDICATE_INVALID", "population predicate structure is invalid"
    )


class FormalFactAsOfEvaluationService(_BaseFormalFactAsOfEvaluationService):
    """Canonical chain-aware formal-fact evaluator used by the HR18 router."""

    @staticmethod
    def _as_date(value):
        if value in (None, ""):
            return None
        if isinstance(value, date):
            return value if not hasattr(value, "date") else value.date()
        return date.fromisoformat(str(value)[:10])

    def _hr04_state(self, fact, revisions):
        if int(fact.tenant_id) != self.tenant_id or not fact.sealed_at:
            raise _source_conflict("HR04 hiring fact tenant/seal is invalid")
        if fact.content_hash != fact.calculate_content_hash():
            raise _source_conflict("HR04 hiring fact content hash does not match sealed payload")
        state = copy.deepcopy(fact.canonical_payload())
        version = 1
        last_effective = fact.accepted_at
        revoked = False
        for revision in revisions:
            if int(revision.tenant_id) != self.tenant_id or revision.fact_id != fact.id:
                raise _source_conflict("HR04 hiring revision crosses fact or tenant boundary")
            if revoked:
                raise _source_conflict("HR04 hiring revision exists after revocation")
            if revision.previous_version != version or revision.new_version != version + 1:
                raise _source_conflict("HR04 hiring revision version chain is broken")
            if revision.before_snapshot_json != state:
                raise _source_conflict("HR04 hiring revision before-snapshot mismatch")
            if not revision.effective_at or revision.effective_at < last_effective:
                raise _source_conflict("HR04 hiring revision effective time is invalid")
            if not revision.sealed_at or revision.content_hash != revision.calculate_content_hash():
                raise _source_conflict("HR04 hiring revision content hash is invalid")
            state = copy.deepcopy(revision.after_snapshot_json or {})
            version = revision.new_version
            last_effective = revision.effective_at
            revoked = state.get("status") == "REVOKED"
        return state

    def _count_hr04(self, population, spec: FormalDomainSpec, as_of_date: date) -> int:
        _assert_chain_quality(tenant_id=self.tenant_id, domain="HR04", as_of_date=as_of_date)
        fact_model = self._model(spec)
        revision_model = _model("hr_recruitment", "HrHiringDecisionRevision")
        if fact_model is None or revision_model is None:
            raise AsOfEvaluationError("ASOF_EVALUATION_SOURCE_UNAVAILABLE", "HR04 hiring Authority chain is unavailable")
        revision_qs = revision_model.objects.filter(tenant_id=self.tenant_id, effective_at__date__lte=as_of_date).order_by("new_version", "effective_at", "id")
        facts = list(fact_model.objects.filter(tenant_id=self.tenant_id, accepted_at__date__lte=as_of_date).order_by("id").prefetch_related(Prefetch("revisions", queryset=revision_qs, to_attr="_hr18_revisions")))
        matched = set()
        for fact in facts:
            state = self._hr04_state(fact, getattr(fact, "_hr18_revisions", []))
            status = str(state.get("status") or "").upper()
            if status == "REVOKED":
                continue
            if status not in {"EFFECTIVE", "CORRECTED"}:
                raise _source_conflict("HR04 hiring state is neither effective nor revoked")
            row = {
                "candidateId": fact.candidate_id,
                "recruitmentPositionId": fact.recruitment_position_id,
                "offerNo": state.get("offerNo"),
                "rank": int(state.get("rank")) if state.get("rank") is not None else None,
                "finalScore": Decimal(str(state.get("finalScore"))) if state.get("finalScore") is not None else None,
                "employmentType": state.get("employmentType") or "",
                "expectedReportDate": self._as_date(state.get("expectedReportDate")),
                "acceptedAt": fact.accepted_at.date(),
                "status": status,
            }
            if _matches_predicate(population.predicate_json, spec, row):
                matched.add(fact.candidate_id)
        return len(matched)

    def _hr05_state(self, snapshot, amendments):
        if int(snapshot.tenant_id) != self.tenant_id or not snapshot.sealed_at:
            raise _source_conflict("HR05 activation fact tenant/seal is invalid")
        if snapshot.content_hash != snapshot.calculate_content_hash():
            raise _source_conflict("HR05 activation fact content hash does not match sealed payload")
        state = copy.deepcopy(snapshot.canonical_payload())
        predecessor = None
        last_effective = snapshot.activated_at
        revoked = False
        for expected_sequence, amendment in enumerate(amendments, start=1):
            if int(amendment.tenant_id) != self.tenant_id or amendment.snapshot_id != snapshot.id:
                raise _source_conflict("HR05 amendment crosses fact or tenant boundary")
            if revoked:
                raise _source_conflict("HR05 amendment exists after revocation")
            if amendment.sequence_no != expected_sequence or amendment.predecessor_id != predecessor:
                raise _source_conflict("HR05 amendment predecessor/sequence chain is broken")
            if amendment.before_snapshot_json != state:
                raise _source_conflict("HR05 amendment before-snapshot mismatch")
            if not amendment.effective_at or amendment.effective_at < last_effective:
                raise _source_conflict("HR05 amendment effective time is invalid")
            if not amendment.sealed_at or amendment.content_hash != amendment.calculate_content_hash():
                raise _source_conflict("HR05 amendment content hash is invalid")
            state = copy.deepcopy(amendment.after_snapshot_json or {})
            predecessor = amendment.id
            last_effective = amendment.effective_at
            revoked = amendment.action == "REVOCATION" or bool(state.get("revoked"))
        return state, revoked

    def _count_hr05(self, population, spec: FormalDomainSpec, as_of_date: date) -> int:
        _assert_chain_quality(tenant_id=self.tenant_id, domain="HR05", as_of_date=as_of_date)
        snapshot_model = self._model(spec)
        amendment_model = _model("hr_onboarding", "HrOnboardingActivationAmendment")
        if snapshot_model is None or amendment_model is None:
            raise AsOfEvaluationError("ASOF_EVALUATION_SOURCE_UNAVAILABLE", "HR05 activation Authority chain is unavailable")
        amendment_qs = amendment_model.objects.filter(tenant_id=self.tenant_id, effective_at__date__lte=as_of_date).order_by("sequence_no", "effective_at", "id")
        snapshots = list(snapshot_model.objects.filter(tenant_id=self.tenant_id, activated_at__date__lte=as_of_date).order_by("id").prefetch_related(Prefetch("amendments", queryset=amendment_qs, to_attr="_hr18_amendments")))
        matched = set()
        for snapshot in snapshots:
            state, revoked = self._hr05_state(snapshot, getattr(snapshot, "_hr18_amendments", []))
            if revoked:
                continue
            staff_id = snapshot.staff_master_id
            if not staff_id:
                raise _source_conflict("HR05 activation fact has no authoritative staff identity")
            row = {
                "personId": snapshot.person_id,
                "staffMasterId": staff_id,
                "employmentId": snapshot.employment_id,
                "assignmentId": snapshot.assignment_id,
                "staffNo": state.get("staffNo") or "",
                "organizationId": state.get("organizationId"),
                "positionId": state.get("positionId"),
                "sourceType": snapshot.source_type or "",
                "sourceId": snapshot.source_id or "",
                "activatedAt": self._as_date(state.get("activatedAt")),
                "status": "EFFECTIVE",
            }
            if _matches_predicate(population.predicate_json, spec, row):
                matched.add(staff_id)
        return len(matched)

    def _count_hr15(self, population, spec: FormalDomainSpec, as_of_date: date) -> int:
        _assert_chain_quality(tenant_id=self.tenant_id, domain="HR15", as_of_date=as_of_date)
        result_model = self._model(spec)
        period_model = _model("hr_payroll", "PayrollPeriod")
        if result_model is None or period_model is None:
            raise AsOfEvaluationError("ASOF_EVALUATION_SOURCE_UNAVAILABLE", "HR15 payroll Authority chain is unavailable")
        results = list(result_model.objects.filter(tenant_id=self.tenant_id, status__in=("FINALIZED", "ADJUSTED", "REVERSED"), effective_at__date__lte=as_of_date).order_by("effective_at", "id"))
        by_id = {result.id: result for result in results}
        successor = {}
        roots = []
        for result in results:
            if result.supersedes_result_id:
                if result.supersedes_result_id in successor:
                    raise _source_conflict("HR15 payroll result chain branches")
                successor[result.supersedes_result_id] = result
            elif result.status == "FINALIZED":
                roots.append(result)
            else:
                raise _source_conflict("HR15 payroll chain has a non-finalized root")
        periods = {p.id: p for p in period_model.objects.filter(tenant_id=self.tenant_id, id__in={r.payroll_period_id for r in roots})}
        matched = set()
        for root in roots:
            gross = Decimal(root.gross_amount)
            deduction = Decimal(root.deduction_amount)
            net = Decimal(root.net_amount)
            current = root
            seen = {root.id}
            while current.id in successor:
                current = successor[current.id]
                if current.id in seen:
                    raise _source_conflict("HR15 payroll result chain contains a cycle")
                seen.add(current.id)
                if current.status == "ADJUSTED":
                    gross += Decimal(current.gross_amount)
                    deduction += Decimal(current.deduction_amount)
                    net += Decimal(current.net_amount)
                elif current.status == "REVERSED":
                    break
            if current.status == "REVERSED":
                continue
            period = periods.get(root.payroll_period_id)
            if period is None:
                raise _source_conflict("HR15 payroll result references a missing/cross-tenant period")
            row = {
                "resultId": current.id,
                "periodId": root.payroll_period_id,
                "periodCode": period.period_code,
                "staffId": root.staff_id,
                "currencyCode": root.currency_code,
                "grossAmount": gross,
                "deductionAmount": deduction,
                "netAmount": net,
                "status": current.status,
                "effectiveAt": current.effective_at.date(),
            }
            if _matches_predicate(population.predicate_json, spec, row):
                matched.add(root.staff_id)
        return len(matched)

    def _count_hr06(self, population, spec: FormalDomainSpec, as_of_date: date) -> int:
        _assert_chain_quality(tenant_id=self.tenant_id, domain="HR06", as_of_date=as_of_date)
        snapshot_model = self._model(spec)
        receipt_model = _model("hr_changes", "HrChangeAuthorityReceipt")
        if snapshot_model is None or receipt_model is None:
            raise AsOfEvaluationError(
                "ASOF_EVALUATION_SOURCE_UNAVAILABLE",
                "HR06 Authority execution chain is not available in this integrated code tree",
            )

        rescinds = receipt_model.objects.filter(
            tenant_id=self.tenant_id,
            change_case_id=OuterRef("change_case_id"),
            kind="ORCHESTRATION_RESCIND",
            effective_at__date__lte=as_of_date,
        )
        queryset = (
            snapshot_model.objects.filter(
                tenant_id=self.tenant_id,
                effective_at__lte=as_of_date,
                change_case_id__tenant_id=self.tenant_id,
                change_case_id__staff_master_id__tenant_id=self.tenant_id,
            )
            .annotate(_hr18_rescinded=Exists(rescinds))
            .filter(_hr18_rescinded=False)
            .filter(_compile_predicate(population.predicate_json, spec))
        )
        return (
            queryset.exclude(change_case_id__staff_master_id__isnull=True)
            .values(spec.identity_field)
            .distinct()
            .count()
        )

    @staticmethod
    def _hr12_base_snapshot(result) -> dict:
        return {
            "sourceResultId": str(result.id),
            "sourceContentHash": result.content_hash,
            "version": int(result.result_version_no),
            "status": result.status,
            "gradeCode": result.grade_code,
            "displayGrade": result.display_grade_snapshot_json or {},
            "calculatedScore": (
                str(result.calculated_score)
                if result.calculated_score is not None
                else None
            ),
            "decisionReason": result.decision_reason or "",
        }

    def _hr12_state(self, result, revisions) -> dict:
        if int(result.tenant_id) != self.tenant_id:
            raise _source_conflict("HR12 result crosses tenant boundary")
        if not result.finalized_at or not result.sealed_at:
            raise _source_conflict("HR12 formal result is missing finalized/sealed time")
        if len(str(result.content_hash or "")) != 64:
            raise _source_conflict("HR12 formal result is missing a sealed content hash")
        calculate_result_hash = getattr(result, "calculate_content_hash", None)
        if callable(calculate_result_hash) and result.content_hash != calculate_result_hash():
            raise _source_conflict("HR12 formal result content hash does not match its sealed payload")
        calculate_calculation_hash = getattr(result, "calculate_calculation_hash", None)
        if callable(calculate_calculation_hash):
            if result.calculation_hash != calculate_calculation_hash():
                raise _source_conflict("HR12 formal result calculation hash does not match its sealed payload")

        state = self._hr12_base_snapshot(result)
        version = int(result.result_version_no)
        last_effective_at = result.finalized_at
        revoked = False
        for revision in revisions:
            if int(revision.tenant_id) != self.tenant_id or revision.result_id != result.id:
                raise _source_conflict("HR12 revision crosses result or tenant boundary")
            if not revision.effective_at or not revision.sealed_at:
                raise _source_conflict("HR12 revision is missing effective/sealed time")
            if revision.effective_at < last_effective_at:
                raise _source_conflict("HR12 revision effective time is not monotonic")
            if revoked:
                raise _source_conflict("HR12 revision exists after result revocation")
            if int(revision.previous_version) != version or int(revision.new_version) != version + 1:
                raise _source_conflict("HR12 result revision version chain is broken")
            if (revision.before_snapshot_json or {}) != state:
                raise _source_conflict("HR12 result revision before-snapshot does not match predecessor")
            after = copy.deepcopy(revision.after_snapshot_json or {})
            if int(after.get("version") or 0) != int(revision.new_version):
                raise _source_conflict("HR12 result revision after-snapshot version is invalid")
            revision_type = str(revision.revision_type or "").upper()
            if revision_type == "CORRECTION" and after.get("status") != "CORRECTED":
                raise _source_conflict("HR12 correction revision does not produce CORRECTED state")
            if revision_type == "REVOCATION" and after.get("status") != "REVOKED":
                raise _source_conflict("HR12 revocation revision does not produce REVOKED state")
            if revision_type not in {"CORRECTION", "REVOCATION"}:
                raise _source_conflict("HR12 result revision type is unsupported")
            if len(str(revision.content_hash or "")) != 64:
                raise _source_conflict("HR12 revision is missing a sealed content hash")
            calculate_revision_hash = getattr(revision, "calculate_content_hash", None)
            if callable(calculate_revision_hash) and revision.content_hash != calculate_revision_hash():
                raise _source_conflict("HR12 revision content hash does not match its sealed payload")
            state = after
            version = int(revision.new_version)
            last_effective_at = revision.effective_at
            revoked = state.get("status") == "REVOKED"
        return state

    def _count_hr12(self, population, spec: FormalDomainSpec, as_of_date: date) -> int:
        _assert_chain_quality(tenant_id=self.tenant_id, domain="HR12", as_of_date=as_of_date)
        result_model = self._model(spec)
        revision_model = _model("hr_assessment", "HrResultRevision")
        case_model = _model("hr_assessment", "HrAssessmentCase")
        if result_model is None or revision_model is None or case_model is None:
            raise AsOfEvaluationError(
                "ASOF_EVALUATION_SOURCE_UNAVAILABLE",
                "HR12 formal result revision chain is not available in this integrated code tree",
            )

        revision_qs = revision_model.objects.filter(
            tenant_id=self.tenant_id,
            effective_at__date__lte=as_of_date,
        ).order_by("new_version", "effective_at", "id")
        results = list(
            result_model.objects.filter(
                tenant_id=self.tenant_id,
                finalized_at__date__lte=as_of_date,
            )
            .order_by("id")
            .prefetch_related(Prefetch("revisions", queryset=revision_qs, to_attr="_hr18_revisions"))
        )
        if not results:
            return 0

        case_ids = {result.case_id for result in results}
        case_rows = list(
            case_model.objects.filter(
                tenant_id=self.tenant_id,
                id__in=case_ids,
            ).values("id", "staff_id", "assessment_type", "cycle_id")
        )
        case_map = {row["id"]: row for row in case_rows}
        if len(case_map) != len(case_ids):
            raise _source_conflict("HR12 formal result references a missing or cross-tenant assessment case")

        matched_staff = set()
        for result in results:
            case = case_map.get(result.case_id)
            if case is None or not case.get("staff_id"):
                raise _source_conflict("HR12 formal result has no authoritative staff identity")
            if str(case.get("assessment_type") or "") != str(result.assessment_type or ""):
                raise _source_conflict("HR12 result assessment type disagrees with its case")
            if case.get("cycle_id") != result.cycle_id:
                raise _source_conflict("HR12 result cycle disagrees with its case")

            state = self._hr12_state(result, getattr(result, "_hr18_revisions", []))
            status = str(state.get("status") or "").upper()
            if status == "REVOKED":
                continue
            if status not in {"FINALIZED", "CORRECTED"}:
                raise _source_conflict("HR12 canonical result state is neither formal nor revoked")

            row = {
                "resultId": result.id,
                "staffId": case["staff_id"],
                "assessmentType": result.assessment_type,
                "cycleId": result.cycle_id,
                "gradeCode": state.get("gradeCode"),
                "status": status,
                "finalizedAt": result.finalized_at.date(),
            }
            if _matches_predicate(population.predicate_json, spec, row):
                matched_staff.add(case["staff_id"])
        return len(matched_staff)

    def _count(
        self,
        population,
        spec: FormalDomainSpec,
        as_of_date: date,
    ) -> int:
        if spec.domain == "HR04":
            return self._count_hr04(population, spec, as_of_date)
        if spec.domain == "HR05":
            return self._count_hr05(population, spec, as_of_date)
        if spec.domain == "HR06":
            return self._count_hr06(population, spec, as_of_date)
        if spec.domain == "HR12":
            return self._count_hr12(population, spec, as_of_date)
        if spec.domain == "HR15":
            return self._count_hr15(population, spec, as_of_date)
        if spec.domain not in _SUCCESSOR_FIELDS:
            return super()._count(population, spec, as_of_date)

        model = self._model(spec)
        if model is None:
            raise AsOfEvaluationError(
                "ASOF_EVALUATION_SOURCE_UNAVAILABLE",
                f"{spec.domain} Authority app is not available in this integrated code tree",
            )

        successor_field = _SUCCESSOR_FIELDS[spec.domain]
        from_field = "effective_date" if spec.domain == "HR16" else "effective_from"
        successors = model.objects.filter(
            tenant_id=self.tenant_id,
            **{f"{from_field}__lte": as_of_date},
            status__in=_SUPERSEDING_STATUSES[spec.domain],
            **{successor_field: OuterRef("pk")},
        )
        queryset = (
            model.objects.filter(
                tenant_id=self.tenant_id,
                **{f"{from_field}__lte": as_of_date},
            )
            .annotate(_hr18_has_effective_successor=Exists(successors))
            .filter(_hr18_has_effective_successor=False)
            .filter(status__in=spec.active_statuses)
        )
        if spec.domain != "HR16":
            queryset = queryset.filter(
                Q(effective_to__isnull=True) | Q(effective_to__gt=as_of_date)
            )
        queryset = queryset.filter(_compile_predicate(population.predicate_json, spec))
        return (
            queryset.exclude(**{f"{spec.identity_field}__isnull": True})
            .values(spec.identity_field)
            .distinct()
            .count()
        )
