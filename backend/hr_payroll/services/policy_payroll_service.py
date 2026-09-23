"""Versioned policy payroll integrated with the existing HR15 authorities.

Trials are read-only monetary previews. A different operator approves a specific
hash. Capture promotes that immutable evidence to the original input ledger;
calculate creates the original PayrollResultFact / lines / contribution facts.
No browser-supplied money is accepted at the calculation boundary.
"""
from __future__ import annotations

import calendar
import json
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID
from django.db import transaction
from django.db.models import Max, Q
from django.utils import timezone
from horilla.hr_event_service import emit_registered_event
from hr_payroll.models import PayrollPeriod, PayrollProfile, PayrollResultFact
from hr_payroll.calculation_models import (PayrollCalculationBatch, PayrollCalculationLine,
                                           PayrollInputSnapshot, SalaryRuleVersion)
from hr_payroll.policy_models import (PayrollBasisVersion, PayrollPolicyVersion, PayrollStandardVersion,
                                     PayrollTrial, PayrollTrialApproval, PayrollWorkloadFact)
from hr_payroll.statutory_models import StatutoryContributionRuleVersion
from .policy_configuration_service import (actor_required, effective_rows, record, verify_configuration)
from .policy_math import PolicyPayrollError, active, allocate_cost, decimal, digest, evaluate_segment, money
from .policy_tax_service import PolicyTaxService

SCHEMA = "hr15-policy-input-v1"


def verify_statutory_rule(rule):
    from .statutory_contribution_service import evidence_hash
    payload = {"ruleCode": rule.rule_code, "versionNo": rule.version_no,
               "group": rule.contribution_group, "code": rule.contribution_code,
               "jurisdiction": rule.jurisdiction_code, "baseVariable": rule.base_variable_key,
               "baseFloor": rule.base_floor, "baseCeiling": rule.base_ceiling,
               "employeeRate": rule.employee_rate, "employerRate": rule.employer_rate,
               "employeeItemCode": rule.employee_item_code, "employerItemCode": rule.employer_item_code,
               "effectiveFrom": rule.effective_from, "effectiveTo": rule.effective_to,
               "policyEvidence": rule.policy_evidence_json}
    if rule.status != "PUBLISHED" or rule.content_hash != evidence_hash(payload):
        raise PolicyPayrollError("PAYROLL_STATUTORY_EVIDENCE_INVALID", "缴费标准未发布或内容被改动")



def jsonable(value):
    return json.loads(json.dumps(value, default=str, ensure_ascii=False))


def _one(rows, code, description):
    if len(rows) != 1:
        raise PolicyPayrollError(code, description + "必须唯一；缺失不能当成零，重叠不能任意取第一条")
    return rows[0]


def trial_digest(trial):
    return digest({"tenantId": trial.tenant_id, "periodId": str(trial.payroll_period_id),
                   "staffId": str(trial.staff_id), "revision": trial.revision_no,
                   "purpose": trial.purpose, "sourceResultId": str(trial.source_result_id or ""),
                   "input": trial.input_payload_json, "output": trial.output_json})


def verify_trial(trial, approved=False):
    if trial.content_hash != trial_digest(trial):
        raise PolicyPayrollError("PAYROLL_TRIAL_TAMPERED", "试算内容校验失败")
    if approved:
        approval = PayrollTrialApproval.objects.filter(tenant_id=trial.tenant_id, trial_id=trial.id).first()
        if (approval is None or approval.decision != "APPROVE" or approval.trial_hash != trial.content_hash
                or approval.created_by is None or approval.created_by == trial.created_by):
            raise PolicyPayrollError("PAYROLL_TRIAL_REVIEW_REQUIRED", "须由另一位授权人员复核此版本试算")
    return trial


def verify_policy_snapshot(snapshot):
    ref = snapshot.source_versions_json
    trial = PayrollTrial.objects.filter(tenant_id=snapshot.tenant_id, id=ref.get("trialId"),
                                        payroll_period_id=snapshot.payroll_period_id, staff_id=snapshot.staff_id).first()
    if not trial:
        raise PolicyPayrollError("PAYROLL_TRIAL_NOT_FOUND", "冻结输入缺少本校原始试算")
    verify_trial(trial, approved=True)
    payload = {"snapshotVersion": SCHEMA, "periodId": str(snapshot.payroll_period_id),
               "staffId": str(snapshot.staff_id), "currencyCode": snapshot.currency_code,
               "sources": ref, "variables": snapshot.variables_json}
    if (snapshot.content_hash != digest(payload) or ref.get("trialHash") != trial.content_hash
            or snapshot.revision_no != trial.revision_no or snapshot.variables_json != {"trialRevision": trial.revision_no}):
        raise PolicyPayrollError("PAYROLL_POLICY_INPUT_TAMPERED", "冻结输入与获批试算版本不一致")
    return trial


def compute_earnings(payload):
    """Recompute only from frozen salary inputs; tax uses a separately frozen quote."""
    totals, traces, metadata = defaultdict(Decimal), defaultdict(list), {}
    first = date.fromisoformat(payload["startDate"])
    last = date.fromisoformat(payload["endDate"])
    denominator = Decimal((last - first).days + 1)
    full_values = {}
    for segment in payload["segments"]:
        start = date.fromisoformat(segment["from"])
        stop = date.fromisoformat(segment["toExclusive"])
        if segment.get("unpaidOutsideRelationship"):
            continue
        evaluated = evaluate_segment(segment["rules"], segment["variables"], segment["selectors"],
                                     segment["standards"], start)
        for item in evaluated:
            rule, raw = item["rule"], item["raw"]
            code, mode = rule["item_code"], rule["allocation_mode"]
            # Consistent type, rounding and allocation for a wage item across the month.
            signature = (rule["item_type"], rule["currency_code"], rule["rounding_mode"], mode)
            if code in metadata and metadata[code]["signature"] != signature:
                raise PolicyPayrollError("PAYROLL_ITEM_SEMANTIC_CHANGE", f"{code}月内计付口径变化，须拆成明确工资项")
            metadata[code] = {"signature": signature, "name": rule["name"], "ruleId": rule["id"]}
            factor = Decimal(1)
            if mode == "CALENDAR_DAYS":
                factor = Decimal((stop - start).days) / denominator
            elif mode == "FULL_PERIOD":
                if code in full_values:
                    if full_values[code] != raw:
                        raise PolicyPayrollError("PAYROLL_FULL_PERIOD_CONFLICT", f"{code}整月计付但月内有不同金额；请明确分段或时点规则")
                    factor = Decimal(0)
                else:
                    full_values[code] = raw
            elif mode == "PERIOD_START":
                factor = Decimal(1 if start == first else 0)
            elif mode == "PERIOD_END":
                factor = Decimal(1 if stop == last + timedelta(days=1) else 0)
            else:
                raise PolicyPayrollError("PAYROLL_ALLOCATION_UNKNOWN", "未知计付方法")
            totals[code] += raw * factor
            traces[code].append({"from": str(start), "toExclusive": str(stop), "days": (stop-start).days,
                                  "monthDays": int(denominator), "allocation": mode, "factor": str(factor),
                                  "ruleId": rule["id"], "ruleHash": rule["content_hash"],
                                  "basisId": segment["basisId"], "policyId": segment["policyId"],
                                  "sourceHashes": {k:v["evidenceHash"] for k,v in segment["sources"].items()},
                                  "formula": item["explanation"]})
    lines=[]
    for code, raw in totals.items():
        item = metadata[code]; kind, currency, rounding, mode = item["signature"]
        lines.append({"itemCode": code, "name": item["name"], "type": kind, "amount": str(money(raw, rounding)),
                      "ruleId": item["ruleId"], "currency": currency, "segments": traces[code],
                      "unrounded": str(raw), "rounding": rounding})
    gross = sum((decimal(x["amount"]) for x in lines if x["type"] == "EARNING"), Decimal(0))
    deductions = sum((decimal(x["amount"]) for x in lines if x["type"] == "DEDUCTION"), Decimal(0))
    employer = sum((decimal(x["amount"]) for x in lines if x["type"] == "EMPLOYER"), Decimal(0))
    return lines, gross, deductions, employer


class PolicyPayrollService:
    def __init__(self, tenant_id, actor_user_id, correlation_id=""):
        self.tenant = int(tenant_id)
        if self.tenant <= 0:
            raise PolicyPayrollError("TENANT_CONTEXT_REQUIRED", "学校上下文缺失")
        self.actor = actor_required(actor_user_id)
        self.correlation_id = correlation_id

    def _period(self, period_id, *, lock=False):
        query = PayrollPeriod.objects.select_for_update() if lock else PayrollPeriod.objects
        period = query.filter(id=period_id, tenant_id=self.tenant).first()
        if period is None or period.engine_version != "POLICY_V1":
            raise PolicyPayrollError("PAYROLL_POLICY_PERIOD_REQUIRED", "须选择本校已明确启用制度核算的期间；旧账不会自动切换")
        if (period.start_date.day != 1 or period.start_date.year != period.end_date.year
                or period.start_date.month != period.end_date.month
                or period.end_date.day != calendar.monthrange(period.start_date.year, period.start_date.month)[1]):
            raise PolicyPayrollError("PAYROLL_MONTH_REQUIRED", "制度核算期间须为完整自然月，月中入离职通过有效区间计付")
        if not period.payment_date:
            raise PolicyPayrollError("PAYROLL_PAYMENT_DATE_REQUIRED", "工资所属期与计划支付日期须分别明确")
        if period.payroll_purpose not in {"REGULAR", "SUPPLEMENT", "ANNUAL_BONUS"}:
            raise PolicyPayrollError("PAYROLL_PURPOSE_INVALID", "核算用途无效")
        return period

    def _published(self, model, **filters):
        objects = list(model.objects.filter(tenant_id=self.tenant, status="PUBLISHED", **filters))
        for obj in objects:
            verify_configuration(obj)
        return [record(obj) for obj in objects]

    def build_input(self, period, staff_id):
        from hr_staff.models import HrStaffMaster, HrEmploymentRelationship, HrStaffAssignment
        from hr_staff.services.effective_dated_query_service import EffectiveDatedQueryService
        from .calculation_service import PayrollCalculationService, PayrollCalculationError
        from .input_fact_provider_registry import PayrollInputProviderRegistry, PayrollInputProviderRegistryError
        from .compensation_change_service import CompensationChangeService

        staff = HrStaffMaster.objects.filter(tenant_id=self.tenant, id=staff_id, person_id__tenant_id=self.tenant).first()
        if staff is None:
            raise PolicyPayrollError("PAYROLL_CANONICAL_STAFF_REQUIRED", "须使用本校正式人员主档，不能临时造工资名单")
        profiles = [record(obj) for obj in PayrollProfile.objects.filter(tenant_id=self.tenant, staff_id=staff.id,
                        status__in=["ACTIVE", "ENDED"], effective_from__lte=period.end_date)
                    .filter(Q(effective_to__isnull=True) | Q(effective_to__gt=period.start_date))]
        if not profiles:
            raise PolicyPayrollError("PAYROLL_PROFILE_NOT_FOUND", "本期间没有发薪身份")
        if any(x["currency_code"] != "CNY" or (x["status"] == "ENDED" and not x["effective_to"]) for x in profiles):
            raise PolicyPayrollError("PAYROLL_PROFILE_INVALID", "发薪身份币种或结束日期无效")
        groups = {x["pay_group_code"] for x in profiles}
        policies = self._published(PayrollPolicyVersion, pay_group_code__in=groups)
        bases = self._published(PayrollBasisVersion, payroll_profile_id__in=[x["id"] for x in profiles], staff_id=staff.id)
        rules = self._published(SalaryRuleVersion, pay_group_code__in=groups)
        standards = self._published(PayrollStandardVersion, pay_group_code__in=groups)
        workloads = self._published(PayrollWorkloadFact, payroll_period_id=period.id, staff_id=staff.id)
        relationships = [record(x) for x in HrEmploymentRelationship.objects.filter(tenant_id=self.tenant, staff_id=staff.id).exclude(status__in=["DRAFT", "CANCELLED"])]
        assignments = [record(x) for x in HrStaffAssignment.objects.filter(tenant_id=self.tenant,
                        employment_relationship_id__tenant_id=self.tenant, employment_relationship_id__staff_id=staff.id).exclude(status__in=["DRAFT", "CANCELLED"])]
        changes = CompensationChangeService(self.tenant, actor_user_id=self.actor).effective_cases(
            staff_id=staff.id, period_start=period.start_date, period_end=period.end_date)
        bounds = {period.start_date, period.end_date + timedelta(days=1)}
        statutory_dates = [record(x) for x in StatutoryContributionRuleVersion.objects.filter(
            tenant_id=self.tenant, status="PUBLISHED", effective_from__lte=period.end_date
        ).filter(Q(effective_to__isnull=True) | Q(effective_to__gt=period.start_date))]
        # A statutory change must not be missed simply because the wage base is constant.
        for row in profiles + policies + bases + rules + standards + relationships + assignments + statutory_dates:
            for key in ("effective_from", "effective_to"):
                if row.get(key):
                    value = date.fromisoformat(row[key])
                    if period.start_date < value <= period.end_date:
                        bounds.add(value)
        for row in changes:
            for value in (row.effective_from, row.effective_to + timedelta(days=1) if row.effective_to else None):
                if value and period.start_date < value <= period.end_date:
                    bounds.add(value)
        bounds = sorted(bounds)
        provider_cache, sources_cache = {}, {}
        history = EffectiveDatedQueryService(self.tenant)
        segments=[]
        for start, stop in zip(bounds, bounds[1:]):
            profile_rows = [x for x in profiles if active(x, start)]
            related = list(history.relationships_as_of(staff.id, start))
            if not profile_rows and not related:
                segments.append({"from": str(start), "toExclusive": str(stop), "unpaidOutsideRelationship": True})
                continue
            profile = _one(profile_rows, "PAYROLL_PROFILE_MISSING_OR_OVERLAP", "当前有效主发薪身份")
            policy = _one(effective_rows([x for x in policies if x["pay_group_code"] == profile["pay_group_code"]], start),
                          "PAYROLL_POLICY_MISSING_OR_OVERLAP", profile["pay_group_code"] + "薪酬制度")
            basis = _one(effective_rows([x for x in bases if x["payroll_profile_id"] == profile["id"]], start),
                         "PAYROLL_BASIS_MISSING_OR_OVERLAP", "个人工资核定")
            selectors = basis["selectors_json"]
            primary_relation = selectors.get("employmentRelationshipId")
            relation = _one([x for x in related if str(x.id) == str(primary_relation)],
                            "PAYROLL_PRIMARY_RELATION_REQUIRED", "核定主发薪用工关系")
            primary = list(history.assignments_for_relationship_as_of(relation.id, start).filter(assignment_type="PRIMARY"))
            assignment = _one(primary, "PAYROLL_PRIMARY_ASSIGNMENT_REQUIRED", "主发薪关系对应的正式主任职")
            if str(assignment.tenant_id) != str(self.tenant):
                raise PolicyPayrollError("PAYROLL_ASSIGNMENT_SCOPE", "任职不属于本校")
            cfg = policy["configuration_json"]
            key = {"REGULAR":"itemCodes", "SUPPLEMENT":"supplementItemCodes", "ANNUAL_BONUS":"bonusItemCodes"}[period.payroll_purpose]
            items = cfg.get(key)
            if not items:
                raise PolicyPayrollError("PAYROLL_PURPOSE_ITEMS_UNAPPROVED", "该制度未明确本次用途的工资项，不能重复套用整月基本工资")
            applicable_rules = [x for x in rules if x["pay_group_code"] == profile["pay_group_code"] and x["item_code"] in items and active(x,start)]
            if set(x["item_code"] for x in applicable_rules) != set(items):
                raise PolicyPayrollError("PAYROLL_RULE_MISSING", "制度工资项缺少有效规则")
            authority_key = tuple(sorted(cfg["requiredAuthorities"]))
            if authority_key not in provider_cache:
                try:
                    provider_cache[authority_key] = PayrollInputProviderRegistry.resolve_all(authority_key)
                except PayrollInputProviderRegistryError as exc:
                    raise PolicyPayrollError("PAYROLL_INPUT_PROVIDER_UNAVAILABLE", str(exc)) from exc
            variables, sources = {}, {}
            for authority, provider in provider_cache[authority_key]:
                source_end = stop - timedelta(days=1) if authority == "HR03" else period.end_date
                cachekey = (authority, str(source_end))
                if cachekey not in sources_cache:
                    request={"schemaVersion": SCHEMA, "authority": authority, "tenantId": self.tenant,
                             "periodId": str(period.id), "periodCode": period.period_code, "staffId":str(staff.id),
                             "startDate":str(period.start_date), "endDate":str(source_end), "asOf":str(source_end),
                             "requiredVariableKeys":[], "correlationId":self.correlation_id}
                    try:
                        source, values = PayrollCalculationService(self.tenant,actor_user_id=self.actor)._normalize_provider_result(authority=authority, request=request, raw=provider.collect(request))
                    except Exception as exc:
                        raise PolicyPayrollError(getattr(exc,"code","PAYROLL_INPUT_PROVIDER_UNAVAILABLE"), f"{authority}依据不可用：{exc}") from exc
                    sources_cache[cachekey] = (source, values)
                source, values = sources_cache[cachekey]
                sources[authority] = source
                for name,value in values.items():
                    if name in variables and variables[name] != value:
                        raise PolicyPayrollError("PAYROLL_VARIABLE_CONFLICT", f"多个权威来源给出不同的{name}")
                    variables[name] = value
            if str(sources["HR03"]["snapshot"].get("person_id")) != str(staff.person_id_id):
                raise PolicyPayrollError("PAYROLL_PERSON_SOURCE_MISMATCH", "HR03自然人身份与工资身份不一致")
            for name,value in basis["variables_json"].items():
                if name in variables and decimal(variables[name]) != decimal(value):
                    raise PolicyPayrollError("PAYROLL_VARIABLE_CONFLICT", f"核定值与来源值冲突：{name}")
                variables[name]=value
            verified_workloads = effective_rows(workloads, period.end_date)
            workload_values = defaultdict(Decimal)
            for row in verified_workloads:
                workload_values[row["variable_key"]] += decimal(row["units"]) * decimal(row["share"]) * decimal(row["coefficient"])
            for name,value in workload_values.items():
                if name in variables:
                    raise PolicyPayrollError("PAYROLL_WORKLOAD_VARIABLE_CONFLICT", f"工作量{name}与其他输入重复")
                variables[name]=str(value)
            if changes:
                try:
                    raw = CompensationChangeService(self.tenant, actor_user_id=self.actor).payroll_input_source(
                        staff_id=staff.id, period_id=period.id, period_start=start, period_end=stop-timedelta(days=1), base_variables=variables)
                    if raw:
                        source, values = PayrollCalculationService(self.tenant,actor_user_id=self.actor)._normalize_provider_result(authority="HR15_CHANGE", request={"tenantId":self.tenant,"periodId":str(period.id),"staffId":str(staff.id)}, raw=raw)
                        sources["HR15_CHANGE"]=source; variables.update(values)
                except Exception as exc:
                    raise PolicyPayrollError(getattr(exc,"code","PAYROLL_CHANGE_INVALID"), str(exc)) from exc
            for value in variables.values():
                decimal(value)
            selected_standards = effective_rows([x for x in standards if x["pay_group_code"]==profile["pay_group_code"]],start)
            segments.append({"from":str(start), "toExclusive":str(stop), "profileId":profile["id"],
                             "profileHash":digest(profile), "payGroupCode":profile["pay_group_code"],
                             "basisId":basis["id"], "basisHash":basis["content_hash"],
                             "policyId":policy["id"], "policyHash":policy["content_hash"], "configuration":cfg,
                             "selectors":selectors, "variables":jsonable(variables), "sources":sources,
                             "rules":applicable_rules,"standards":selected_standards,
                             "employment":record(relation), "assignment":record(assignment),
                             "taxDeductions":basis["tax_deductions_json"],"costShares":basis["cost_shares_json"],
                             "verifiedWorkloads":verified_workloads})
        payable = [s for s in segments if not s.get("unpaidOutsideRelationship")]
        if not payable:
            raise PolicyPayrollError("PAYROLL_NO_PAYABLE_RELATION", "所属期无有效发薪关系，历史补欠须引用原工资结果")
        # One payment cannot mix withholding agents or tax treatments implicitly.
        def tax_mode(s):
            return s["configuration"].get("bonusTaxMethod") if period.payroll_purpose=="ANNUAL_BONUS" else s["configuration"]["taxMethod"]
        modes = {(s["configuration"]["withholdingAgent"], tax_mode(s)) for s in payable}
        if len(modes)!=1:
            raise PolicyPayrollError("PAYROLL_TAX_ENTITY_CHANGED", "月内扣缴主体或税目变化，须分开明确核算，不可合并套算")
        # Tax deduction / cost inputs are payment-level approved facts, not calendar-day multipliers.
        tail=payable[-1]
        if any(s["taxDeductions"] != tail["taxDeductions"] or s["costShares"] != tail["costShares"] for s in payable):
            raise PolicyPayrollError("PAYROLL_PAYMENT_BASIS_CONFLICT", "同一支付的税务累计或经费分摊资料不一致，先统一核定支付口径")
        payload={"schema":SCHEMA,"tenantId":self.tenant,"periodId":str(period.id),"periodCode":period.period_code,
                 "staffId":str(staff.id),"personId":str(staff.person_id_id),"startDate":str(period.start_date),
                 "endDate":str(period.end_date),"paymentDate":str(period.payment_date),"payrollPurpose":period.payroll_purpose,
                 "segments":segments,"taxMethod":tax_mode(tail),"withholdingAgent":tail["configuration"]["withholdingAgent"],
                 "taxDeductions":tail["taxDeductions"],"costShares":tail["costShares"],
                 "paymentProfileId":tail["profileId"],
                 "paymentAccountHash":digest({"tenant":self.tenant,"ref":next(x["payment_account_ref"] for x in profiles if x["id"]==tail["profileId"])}),
                 "statutory":self._statutory(period,payable)}
        return jsonable(payload)

    def _statutory(self,period,segments):
        from .statutory_contribution_service import StatutoryContributionService
        applicable=[]
        signatures=set()
        for segment in segments:
            cfg=segment["configuration"]
            if period.payroll_purpose != "REGULAR":
                # Monthly contributions already belong to the regular wage period;
                # supplements/bonus cannot silently collect the same month again.
                signatures.add("SUPPLEMENT_NO_DUPLICATE_MONTHLY_CONTRIBUTION");continue
            if cfg["statutoryMode"]=="NOT_APPLICABLE":
                signatures.add("N/A:"+cfg["statutoryReason"]);continue
            jurisdiction=segment["selectors"].get("statutoryJurisdiction")
            if not jurisdiction:
                raise PolicyPayrollError("PAYROLL_STATUTORY_JURISDICTION_REQUIRED","须核定参保地区，不能混用地方政策")
            rows=[]
            for code in cfg["statutoryCodes"]:
                choices=list(StatutoryContributionRuleVersion.objects.filter(tenant_id=self.tenant,status="PUBLISHED",
                     rule_code=code,jurisdiction_code=jurisdiction,effective_from__lte=date.fromisoformat(segment["from"]))
                     .filter(Q(effective_to__isnull=True)|Q(effective_to__gt=date.fromisoformat(segment["from"]))))
                rule=_one(choices,"PAYROLL_STATUTORY_RULE_MISSING_OR_OVERLAP","适用缴费标准"+code)
                # The original service verifies published rule evidence.
                verify_statutory_rule(rule)
                try:
                    calculated=StatutoryContributionService.calculate(rule,segment["variables"])
                except Exception as exc:
                    from .statutory_contribution_service import StatutoryContributionError
                    if not isinstance(exc, StatutoryContributionError):
                        raise
                    raise PolicyPayrollError(exc.code, str(exc)) from exc
                rows.append({"rule":record(rule),"requestedBase":str(calculated.requested_base),
                             "contributionBase":str(calculated.contribution_base),"employeeAmount":str(calculated.employee_amount),
                             "employerAmount":str(calculated.employer_amount)})
            signatures.add(digest(rows));applicable=rows
        if len(signatures)>1:
            raise PolicyPayrollError("PAYROLL_STATUTORY_MONTH_CHANGE_REQUIRES_REVIEW", "月内缴费身份/基数/地区变化，需核定整月缴费归属，不擅自按工资天数折算社保")
        return applicable

    def evaluate(self,payload):
        lines,gross,deduction,employer=compute_earnings(payload)
        item_codes={x["itemCode"] for x in lines}
        for entry in payload["statutory"]:
            rule=entry["rule"]
            for payer,amount,code,kind in (("个人",entry["employeeAmount"],rule["employee_item_code"],"DEDUCTION"),
                                           ("单位",entry["employerAmount"],rule["employer_item_code"],"EMPLOYER")):
                if code in item_codes or code=="IIT":
                    raise PolicyPayrollError("PAYROLL_ITEM_CONFLICT","缴费工资项与其他项目重复")
                item_codes.add(code)
                lines.append({"itemCode":code,"name":rule["name"]+"（"+payer+"）","type":kind,"amount":amount,
                              "ruleId":rule["id"],"currency":"CNY","statutory":entry})
            deduction+=decimal(entry["employeeAmount"]);employer+=decimal(entry["employerAmount"])
        if gross<0 or deduction<0:
            raise PolicyPayrollError("PAYROLL_NEGATIVE_REGULAR_RESULT","负工资须走有依据的补扣流程")
        tax_data={"personId":payload["personId"],"withholdingAgent":payload["withholdingAgent"],
                  "paymentDate":payload["paymentDate"],"method":payload["taxMethod"],"income":str(gross),
                  "exemptIncome":payload["taxDeductions"].get("exemptIncome","0"),"deductions":payload["taxDeductions"]}
        quote=PolicyTaxService(self.tenant,self.actor).quote(tax_data)
        tax=decimal(quote["withholding"]);deduction+=tax
        lines.append({"itemCode":"IIT","name":"个人所得税预扣","type":"DEDUCTION","amount":str(tax),
                      "currency":"CNY","ruleId":None,"taxQuote":quote})
        net=gross-deduction
        if net<0:
            raise PolicyPayrollError("PAYROLL_NEGATIVE_NET","实发为负，需核定债务/抵扣，不自动发负工资")
        cost=gross+employer
        return jsonable({"lines":lines,"gross":str(money(gross)),"deduction":str(money(deduction)),
                         "net":str(money(net)),"employerCost":str(money(employer)),"totalCost":str(money(cost)),
                         "costAllocation":allocate_cost(cost,payload["costShares"]) if payload["costShares"] else {},
                         "taxInput":tax_data,"taxQuote":quote})

    @transaction.atomic
    def trial(self, *, period_id, staff_id, idempotency_key):
        if not isinstance(idempotency_key,str) or not 1<=len(idempotency_key)<=128:
            raise PolicyPayrollError("PAYROLL_IDEMPOTENCY_REQUIRED","须提供本次试算业务键")
        period=self._period(period_id,lock=True)
        existing=PayrollTrial.objects.filter(tenant_id=self.tenant,idempotency_key=idempotency_key).first()
        if existing:
            if str(existing.payroll_period_id)!=str(period.id) or str(existing.staff_id)!=str(staff_id) or existing.purpose!="NORMAL":
                raise PolicyPayrollError("PAYROLL_TRIAL_IDEMPOTENCY_CONFLICT","业务键已用于其他人员/期间/用途")
            return verify_trial(existing)
        if period.status not in {"OPEN","INPUT_FROZEN"}:
            raise PolicyPayrollError("PAYROLL_TRIAL_PERIOD_LOCKED","已有正式核算结果的期间不再重算覆盖；请走追溯更正")
        payload=self.build_input(period,staff_id);output=self.evaluate(payload)
        revision=(PayrollTrial.objects.filter(tenant_id=self.tenant,payroll_period_id=period.id,staff_id=staff_id).aggregate(n=Max("revision_no"))["n"] or 0)+1
        trial=PayrollTrial(tenant_id=self.tenant,created_by=self.actor,updated_by=self.actor,payroll_period_id=period.id,
                           staff_id=staff_id,revision_no=revision,idempotency_key=idempotency_key,input_payload_json=payload,output_json=output)
        trial.content_hash=trial_digest(trial);trial.save()
        emit_registered_event(tenant_id=self.tenant,event_name="hr.payroll.trial.created",payload={"trialId":str(trial.id),"contentHash":trial.content_hash,"actorId":self.actor},correlation_id=self.correlation_id)
        return trial

    @transaction.atomic
    def approve(self, *, trial_id, expected_hash, decision="APPROVE", note):
        trial=PayrollTrial.objects.filter(tenant_id=self.tenant,id=trial_id).first()
        if not trial:
            raise PolicyPayrollError("PAYROLL_TRIAL_NOT_FOUND","本校试算不存在")
        period=self._period(trial.payroll_period_id,lock=True)
        verify_trial(trial)
        if trial.content_hash!=expected_hash:
            raise PolicyPayrollError("PAYROLL_TRIAL_VERSION_CHANGED","复核内容版本不一致")
        old=PayrollTrialApproval.objects.filter(tenant_id=self.tenant,trial_id=trial.id).first()
        if old:
            if old.trial_hash==expected_hash and old.decision==decision and old.created_by==self.actor:
                return old
            raise PolicyPayrollError("PAYROLL_REVIEW_ALREADY_RECORDED","该版本已有正式复核结论")
        if trial.created_by==self.actor:
            raise PolicyPayrollError("PAYROLL_SEPARATION_OF_DUTIES","经办与复核须为不同人员")
        if not str(note).strip() or decision not in {"APPROVE","REJECT"}:
            raise PolicyPayrollError("PAYROLL_REVIEW_NOTE_REQUIRED","须明确复核结论和说明")
        if period.status not in {"OPEN","INPUT_FROZEN"}:
            raise PolicyPayrollError("PAYROLL_REVIEW_PERIOD_LOCKED","期间已正式核算，不再复核旧试算")
        if decision=="APPROVE":
            payload=self.build_input(period,trial.staff_id)
            if payload!=trial.input_payload_json or self.evaluate(payload)!=trial.output_json:
                raise PolicyPayrollError("PAYROLL_TRIAL_STALE","人员、规则、输入或税账已变化，请新建试算版本后复核")
        approval=PayrollTrialApproval.objects.create(tenant_id=self.tenant,created_by=self.actor,updated_by=self.actor,
                    trial_id=trial.id,trial_hash=expected_hash,decision=decision,note=str(note).strip())
        emit_registered_event(tenant_id=self.tenant,event_name="hr.payroll.trial.approved",payload={"trialId":str(trial.id),"decision":decision,"trialHash":expected_hash,"actorId":self.actor},correlation_id=self.correlation_id)
        return approval

    @transaction.atomic
    def capture(self, *, period_id, staff_id):
        period=self._period(period_id,lock=True)
        if period.status!="INPUT_FROZEN":
            raise PolicyPayrollError("PAYROLL_INPUT_NOT_FROZEN","须先冻结期间输入")
        trial=PayrollTrial.objects.filter(tenant_id=self.tenant,payroll_period_id=period.id,staff_id=staff_id,purpose="NORMAL").order_by("-revision_no").first()
        if not trial:
            raise PolicyPayrollError("PAYROLL_TRIAL_REQUIRED","先试算并复核，再冻结正式工资输入")
        verify_trial(trial,approved=True)
        # A stale review cannot be promoted. Frozen old revisions remain intact.
        payload=self.build_input(period,staff_id)
        if payload!=trial.input_payload_json or self.evaluate(payload)!=trial.output_json:
            raise PolicyPayrollError("PAYROLL_TRIAL_STALE","获批后来源变化，须重新试算复核")
        existing=PayrollInputSnapshot.objects.filter(tenant_id=self.tenant,payroll_period_id=period.id,staff_id=staff_id,revision_no=trial.revision_no).first()
        if existing:
            verify_policy_snapshot(existing);return existing
        sources={"trialId":str(trial.id),"trialHash":trial.content_hash}
        variables={"trialRevision":trial.revision_no}
        content={"snapshotVersion":SCHEMA,"periodId":str(period.id),"staffId":str(staff_id),"currencyCode":"CNY","sources":sources,"variables":variables}
        return PayrollInputSnapshot.objects.create(tenant_id=self.tenant,created_by=self.actor,updated_by=self.actor,
                     payroll_period_id=period.id,staff_id=staff_id,revision_no=trial.revision_no,currency_code="CNY",
                     snapshot_version=SCHEMA,source_versions_json=sources,variables_json=variables,content_hash=digest(content),captured_at=timezone.now())

    @transaction.atomic
    def calculate(self, *, period_id,batch_no,idempotency_key):
        from .calculation_service import PayrollCalculationOutcome,verify_payroll_result_input_evidence
        from .statutory_contribution_service import StatutoryContributionService
        period=self._period(period_id,lock=True)
        if not batch_no or not idempotency_key:
            raise PolicyPayrollError("PAYROLL_IDEMPOTENCY_REQUIRED","批次号和业务键不可为空")
        existing=PayrollCalculationBatch.objects.filter(tenant_id=self.tenant,idempotency_key=idempotency_key).first()
        if existing:
            if existing.payroll_period_id!=period.id or existing.batch_no!=batch_no or existing.status!="COMPLETED":
                raise PolicyPayrollError("PAYROLL_CALCULATION_IDEMPOTENCY_CONFLICT","业务键已占用或核算未完成")
            result_ids=PayrollCalculationLine.objects.filter(tenant_id=self.tenant,calculation_batch_id=existing.id).values_list("payroll_result_id",flat=True).distinct()
            results=list(PayrollResultFact.objects.filter(tenant_id=self.tenant,payroll_period_id=period.id,id__in=result_ids))
            if len(results)!=existing.result_count:
                raise PolicyPayrollError("PAYROLL_CALCULATION_EVIDENCE_MISSING","核算结果数量不一致")
            for result in results:verify_payroll_result_input_evidence(result)
            return PayrollCalculationOutcome(existing,tuple(str(x.id) for x in results))
        if period.status!="INPUT_FROZEN" or PayrollResultFact.objects.filter(tenant_id=self.tenant,payroll_period_id=period.id).exists():
            raise PolicyPayrollError("PAYROLL_PERIOD_RESULT_CONFLICT","期间不允许生成第二套正式工资")
        snapshots={}
        for snapshot in PayrollInputSnapshot.objects.filter(tenant_id=self.tenant,payroll_period_id=period.id).order_by("staff_id","revision_no"):
            snapshots[str(snapshot.staff_id)]=snapshot
        if not snapshots:raise PolicyPayrollError("PAYROLL_INPUT_REQUIRED","无获批冻结输入")
        if period.payroll_purpose=="REGULAR":
            expected={str(x) for x in PayrollProfile.objects.filter(tenant_id=self.tenant,status__in=["ACTIVE","ENDED"],effective_from__lte=period.end_date)
                      .filter(Q(effective_to__isnull=True)|Q(effective_to__gt=period.start_date)).values_list("staff_id",flat=True)}
            if set(snapshots)!=expected:
                raise PolicyPayrollError("PAYROLL_ROSTER_INCOMPLETE","冻结名单与有效发薪名单不一致，不允许漏人后按全期成功封账")
        trials=[]
        for snapshot in snapshots.values():
            trial=verify_policy_snapshot(snapshot)
            newest=PayrollTrial.objects.filter(tenant_id=self.tenant,payroll_period_id=period.id,staff_id=snapshot.staff_id,purpose="NORMAL").order_by("-revision_no").first()
            if newest.id!=trial.id:
                raise PolicyPayrollError("PAYROLL_INPUT_REVISION_STALE","已有更高试算修订，须获批并重新冻结")
            if self.build_input(period,snapshot.staff_id)!=trial.input_payload_json or self.evaluate(trial.input_payload_json)!=trial.output_json:
                raise PolicyPayrollError("PAYROLL_INPUT_STALE","正式核算前依据或税账已变化，不沿用过期获批金额")
            trials.append((snapshot,trial))
        batch=PayrollCalculationBatch.objects.create(tenant_id=self.tenant,created_by=self.actor,updated_by=self.actor,
                     payroll_period_id=period.id,batch_no=batch_no,idempotency_key=idempotency_key,status="RUNNING",
                     staff_count=len(trials),started_at=timezone.now(),rule_set_hash=digest([t.content_hash for _,t in trials]))
        total_g=Decimal(0);total_d=Decimal(0);total_n=Decimal(0);ids=[]
        statutory=StatutoryContributionService(self.tenant,actor_user_id=self.actor)
        for snapshot,trial in trials:
            out=trial.output_json
            result=PayrollResultFact.objects.create(tenant_id=self.tenant,created_by=self.actor,updated_by=self.actor,
                result_no=f"POL-{period.id.hex[:16]}-{snapshot.staff_id.hex[:16]}",payroll_period_id=period.id,staff_id=snapshot.staff_id,
                currency_code="CNY",gross_amount=decimal(out["gross"]),deduction_amount=decimal(out["deduction"]),net_amount=decimal(out["net"]),status="DRAFT")
            PolicyTaxService(self.tenant,self.actor).reserve(result=result,data=out["taxInput"],approved_quote=out["taxQuote"])
            facts={}
            for entry in trial.input_payload_json["statutory"]:
                rule=StatutoryContributionRuleVersion.objects.get(tenant_id=self.tenant,id=entry["rule"]["id"])
                calculated=statutory.calculate(rule,{rule.base_variable_key:entry["requestedBase"]})
                if str(calculated.employee_amount)!=entry["employeeAmount"] or str(calculated.employer_amount)!=entry["employerAmount"]:
                    raise PolicyPayrollError("PAYROLL_STATUTORY_CHANGED","缴费依据变化")
                fact=statutory.create_fact(calculated=calculated,period=period,result=result,batch=batch,snapshot=snapshot)
                facts[str(rule.id)]=fact
            for seq,line in enumerate(out["lines"],1):
                evidence={"policyEngine":SCHEMA,"trialId":str(trial.id),"trialHash":trial.content_hash,
                          "inputSnapshotId":str(snapshot.id),"inputContentHash":snapshot.content_hash,"calculation":line,
                          "costAllocation":out["costAllocation"]}
                if line.get("statutory"):
                    fact=facts[line["ruleId"]]
                    evidence.update(contributionFactId=str(fact.id),authority="HR15_STATUTORY_CONTRIBUTION",evidenceHash=fact.evidence_hash)
                PayrollCalculationLine.objects.create(tenant_id=self.tenant,created_by=self.actor,updated_by=self.actor,
                     calculation_batch_id=batch.id,payroll_result_id=result.id,staff_id=snapshot.staff_id,
                     item_code=line["itemCode"],item_name=line["name"],item_type=line["type"],sequence_no=seq,
                     amount=decimal(line["amount"]),currency_code="CNY",rule_version_id=line.get("ruleId"),explanation_json=evidence)
            total_g+=result.gross_amount;total_d+=result.deduction_amount;total_n+=result.net_amount;ids.append(str(result.id))
        batch.status="COMPLETED";batch.result_count=len(ids);batch.gross_total=total_g;batch.deduction_total=total_d;batch.net_total=total_n;batch.completed_at=timezone.now();batch.save()
        period.status="CALCULATED";period.updated_by=self.actor;period.save(update_fields=["status","updated_by","updated_at"])
        emit_registered_event(tenant_id=self.tenant,event_name="hr.payroll.calculation.completed",payload={"periodId":str(period.id),"batchId":str(batch.id),"resultIds":ids,"ruleSetHash":batch.rule_set_hash,"policyEngine":SCHEMA},correlation_id=self.correlation_id)
        return PayrollCalculationOutcome(batch,tuple(ids))


def policy_finalization_sources(period):
    """Explicit policy dependencies replace the legacy unconditional HR11 gate."""
    trials=[];required=set()
    snapshots={}
    for s in PayrollInputSnapshot.objects.filter(tenant_id=period.tenant_id,payroll_period_id=period.id).order_by("revision_no"):
        snapshots[str(s.staff_id)]=s
    if not snapshots:raise PolicyPayrollError("PAYROLL_INPUT_REQUIRED","无制度输入凭证")
    for s in snapshots.values():
        trial=verify_policy_snapshot(s);trials.append({"trialId":str(trial.id),"hash":trial.content_hash})
        for segment in trial.input_payload_json["segments"]:
            if not segment.get("unpaidOutsideRelationship"):
                required.update(segment["configuration"]["requiredAuthorities"])
    return {"policyEngine":SCHEMA,"requiredAuthorities":sorted(required),"trialEvidence":trials}
