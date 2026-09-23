"""Reviewed school-policy, standard, salary-qualification and workload configuration."""
from __future__ import annotations

from datetime import date
from django.db import transaction
from django.db.models import Max, Q
from django.utils import timezone
from hr_payroll.models import PayrollPeriod, PayrollProfile
from hr_payroll.calculation_models import SalaryRuleVersion
from hr_payroll.policy_models import (PayrollBasisVersion, PayrollPolicyScope, PayrollPolicyVersion,
                                     PayrollStandardVersion, PayrollWorkloadFact)
from .policy_math import PolicyPayrollError, active, allocate_cost, decimal, digest, validate_formula_definition

MODELS = {"POLICY": PayrollPolicyVersion, "STANDARD": PayrollStandardVersion,
          "BASIS": PayrollBasisVersion, "WORKLOAD": PayrollWorkloadFact, "RULE": SalaryRuleVersion}
ALLOCATION_MODES = {"CALENDAR_DAYS", "FULL_PERIOD", "PERIOD_START", "PERIOD_END"}


def record(obj):
    result = {}
    for field in obj._meta.concrete_fields:
        value = getattr(obj, field.attname)
        if isinstance(value, (dict, list, str, bool, int)) or value is None:
            result[field.attname] = value
        else:
            result[field.attname] = str(value)
    return result


def content_payload(obj):
    excluded = {"id", "created_at", "updated_at", "created_by", "updated_by", "content_hash",
                "status", "published_by", "published_at"}
    return {key: value for key, value in record(obj).items() if key not in excluded}


def verify_configuration(obj):
    if obj.status != "PUBLISHED" or not obj.content_hash or digest(content_payload(obj)) != obj.content_hash:
        raise PolicyPayrollError("PAYROLL_POLICY_EVIDENCE_INVALID", "政策或核定记录未发布或内容校验失败")


def effective_rows(rows, on):
    """A reviewed explicit successor shadows its ancestors only inside its own interval."""
    by_id = {str(row["id"]): row for row in rows}
    candidates = [row for row in rows if active(row, on)]
    shadowed = set()
    for row in candidates:
        parent = str(row.get("supersedes_id") or "")
        seen = set()
        while parent:
            if parent in seen or parent not in by_id:
                raise PolicyPayrollError("PAYROLL_POLICY_CHAIN_INVALID", "政策替代链缺失或循环")
            seen.add(parent); shadowed.add(parent)
            parent = str(by_id[parent].get("supersedes_id") or "")
    return [row for row in candidates if str(row["id"]) not in shadowed]


def actor_required(actor):
    if isinstance(actor, bool) or not actor or int(actor) <= 0:
        raise PolicyPayrollError("PAYROLL_ACTOR_REQUIRED", "必须由认证用户办理")
    return int(actor)


class PolicyConfigurationService:
    def __init__(self, tenant_id, actor_user_id, correlation_id=""):
        if not tenant_id or int(tenant_id) <= 0:
            raise PolicyPayrollError("TENANT_CONTEXT_REQUIRED", "学校上下文缺失")
        self.tenant_id = int(tenant_id)
        self.actor = actor_required(actor_user_id)
        self.correlation_id = correlation_id

    def _scope(self, key):
        obj, _ = PayrollPolicyScope.objects.get_or_create(tenant_id=self.tenant_id, scope_key=key)
        return PayrollPolicyScope.objects.select_for_update().get(pk=obj.pk, tenant_id=self.tenant_id)

    @staticmethod
    def _date(value, name, optional=False):
        if optional and not value:
            return None
        try:
            return date.fromisoformat(str(value))
        except (TypeError, ValueError) as exc:
            raise PolicyPayrollError("PAYROLL_DATE_INVALID", f"{name}须为年月日") from exc

    def _key(self, kind, obj):
        if kind in {"POLICY", "STANDARD", "RULE"}:
            return "GROUP:" + obj.pay_group_code
        if kind == "BASIS":
            return "PROFILE:" + str(obj.payroll_profile_id)
        return "WORKLOAD:" + str(obj.payroll_period_id)

    def _peers(self, kind, obj):
        qs = type(obj).objects.filter(tenant_id=self.tenant_id)
        if kind == "POLICY":
            return qs.filter(pay_group_code=obj.pay_group_code)
        if kind == "STANDARD":
            return qs.filter(pay_group_code=obj.pay_group_code, table_code=obj.table_code, level_code=obj.level_code)
        if kind == "BASIS":
            return qs.filter(payroll_profile_id=obj.payroll_profile_id)
        if kind == "RULE":
            return qs.filter(pay_group_code=obj.pay_group_code, item_code=obj.item_code)
        return qs.filter(payroll_period_id=obj.payroll_period_id, workload_key=obj.workload_key, staff_id=obj.staff_id)

    @transaction.atomic
    def create(self, kind, data):
        kind = str(kind).upper()
        if kind not in MODELS or not isinstance(data, dict):
            raise PolicyPayrollError("PAYROLL_CONFIGURATION_KIND_INVALID", "配置类型不合法")
        model = MODELS[kind]
        allowed = {"effectiveFrom", "effectiveTo", "evidenceRef", "supersedesId"}
        fields_by_kind = {
            "POLICY": {"payGroupCode", "name", "configuration"},
            "STANDARD": {"payGroupCode", "tableCode", "levelCode", "amount", "currencyCode"},
            "BASIS": {"payrollProfileId", "selectors", "variables", "taxDeductions", "costShares"},
            "WORKLOAD": {"periodId", "staffId", "workloadKey", "variableKey", "units", "share", "coefficient"},
            "RULE": {"payGroupCode", "ruleCode", "itemCode", "name", "itemType", "priority", "currencyCode", "formula", "dependencies", "roundingMode", "allocationMode"},
        }
        if set(data) - allowed - fields_by_kind[kind]:
            raise PolicyPayrollError("PAYROLL_CONFIGURATION_UNKNOWN_FIELD", "存在未识别字段：" + ",".join(sorted(set(data) - allowed - fields_by_kind[kind])))
        start = self._date(data.get("effectiveFrom"), "生效日")
        end = self._date(data.get("effectiveTo"), "失效日", True)
        if end and end <= start:
            raise PolicyPayrollError("PAYROLL_DATE_RANGE_INVALID", "生效区间须为左闭右开，失效日大于生效日")
        evidence = str(data.get("evidenceRef") or "").strip()
        if not evidence:
            raise PolicyPayrollError("PAYROLL_EVIDENCE_REQUIRED", "必须填写核定或政策依据")
        shared = dict(tenant_id=self.tenant_id, created_by=self.actor, updated_by=self.actor,
                      effective_from=start, effective_to=end)
        if kind != "RULE":
            shared.update(evidence_ref=evidence, supersedes_id=data.get("supersedesId") or None)
        group = str(data.get("payGroupCode") or "").strip().upper()
        if kind in {"POLICY", "STANDARD", "RULE"} and not group:
            raise PolicyPayrollError("PAYROLL_GROUP_REQUIRED", "必须选择原薪酬组")
        if kind == "POLICY":
            obj = model(**shared, pay_group_code=group, name=str(data.get("name") or "").strip(), configuration_json=data.get("configuration", {}))
            self._validate_policy(obj)
        elif kind == "STANDARD":
            obj = model(**shared, pay_group_code=group, table_code=str(data.get("tableCode") or "").strip(),
                        level_code=str(data.get("levelCode") or "").strip(), amount=decimal(data.get("amount")), currency_code=str(data.get("currencyCode") or "CNY"))
            if not obj.table_code or not obj.level_code or obj.amount < 0 or obj.currency_code != "CNY":
                raise PolicyPayrollError("PAYROLL_STANDARD_INVALID", "标准表、等级、非负金额及人民币币种必须有效")
        elif kind == "BASIS":
            profile = PayrollProfile.objects.filter(tenant_id=self.tenant_id, id=data.get("payrollProfileId")).first()
            if not profile:
                raise PolicyPayrollError("PAYROLL_PROFILE_NOT_FOUND", "薪酬身份不属于本校或不存在")
            obj = model(**shared, payroll_profile_id=profile.id, staff_id=profile.staff_id,
                        selectors_json=data.get("selectors", {}), variables_json=data.get("variables", {}),
                        tax_deductions_json=data.get("taxDeductions", {}), cost_shares_json=data.get("costShares", {}))
            for values in (obj.variables_json, obj.selectors_json, obj.tax_deductions_json, obj.cost_shares_json):
                if not isinstance(values, dict):
                    raise PolicyPayrollError("PAYROLL_BASIS_INVALID", "核定分类和输入须为对象")
            for key, value in obj.variables_json.items():
                if not key or len(key) > 64:
                    raise PolicyPayrollError("PAYROLL_BASIS_INVALID", "核定输入名称不合法")
                decimal(value, key)
            if obj.cost_shares_json:
                allocate_cost("1.00", obj.cost_shares_json)
        elif kind == "WORKLOAD":
            from hr_staff.models import HrStaffMaster
            period = PayrollPeriod.objects.filter(tenant_id=self.tenant_id, id=data.get("periodId")).first()
            staff = HrStaffMaster.objects.filter(tenant_id=self.tenant_id, id=data.get("staffId")).first()
            if not period or not staff:
                raise PolicyPayrollError("PAYROLL_WORKLOAD_SCOPE_INVALID", "工作量期间或教职工不属于本校")
            obj = model(**shared, payroll_period_id=period.id, staff_id=staff.id,
                        workload_key=str(data.get("workloadKey") or "").strip(), variable_key=str(data.get("variableKey") or "").strip(),
                        units=decimal(data.get("units")), share=decimal(data.get("share")), coefficient=decimal(data.get("coefficient")))
            if not obj.workload_key or not obj.variable_key or obj.units < 0 or not 0 < obj.share <= 1 or obj.coefficient < 0:
                raise PolicyPayrollError("PAYROLL_WORKLOAD_INVALID", "课次/成果标识、核定数量、分担比例或系数不合法")
        else:
            if data.get("supersedesId"):
                raise PolicyPayrollError("PAYROLL_RULE_EXPLICIT_DATES_REQUIRED", "工资规则版本先使用明确的不重叠有效区间")
            formula = data.get("formula", {})
            validate_formula_definition(formula)
            formula = {**formula, "policyEvidenceRef": evidence}
            obj = model(**shared, pay_group_code=group, rule_code=str(data.get("ruleCode") or "").strip(),
                        item_code=str(data.get("itemCode") or "").strip(), name=str(data.get("name") or "").strip(),
                        item_type=str(data.get("itemType") or "EARNING"), priority=int(data.get("priority", 100)),
                        currency_code=str(data.get("currencyCode") or "CNY"), formula_json=formula,
                        dependencies_json=data.get("dependencies", []), rounding_mode=str(data.get("roundingMode") or "HALF_UP"),
                        allocation_mode=str(data.get("allocationMode") or "FULL_PERIOD"))
            if (not obj.rule_code or not obj.item_code or obj.item_code in {"IIT", "__TAX__"}
                    or obj.item_type not in {"EARNING", "DEDUCTION", "EMPLOYER"}
                    or obj.currency_code != "CNY" or obj.allocation_mode not in ALLOCATION_MODES
                    or obj.rounding_mode not in {"HALF_UP", "HALF_EVEN", "DOWN"}
                    or not isinstance(obj.dependencies_json, list)
                    or any(not isinstance(d, str) or not d for d in obj.dependencies_json)
                    or len(set(obj.dependencies_json)) != len(obj.dependencies_json)):
                raise PolicyPayrollError("PAYROLL_RULE_INVALID", "工资项、分摊方式、依赖或舍入配置不合法")
        self._scope(self._key(kind, obj))
        obj.version_no = (self._peers(kind, obj).aggregate(n=Max("version_no"))["n"] or 0) + 1
        obj.full_clean()
        obj.save()
        return obj

    @staticmethod
    def _validate_policy(obj):
        cfg = obj.configuration_json
        allowed = {"requiredAuthorities", "itemCodes", "taxMethod", "withholdingAgent", "statutoryMode",
                   "statutoryCodes", "statutoryReason", "supplementItemCodes", "bonusItemCodes", "bonusTaxMethod"}
        if not isinstance(cfg, dict) or set(cfg) - allowed:
            raise PolicyPayrollError("PAYROLL_POLICY_INVALID", "政策字段不合法")
        authorities = cfg.get("requiredAuthorities")
        items = cfg.get("itemCodes")
        if (not obj.name or not isinstance(authorities, list) or "HR03" not in authorities
                or len(set(authorities)) != len(authorities)
                or any(not isinstance(a, str) or not a for a in authorities)
                or not isinstance(items, list) or not items or len(items) != len(set(items))
                or any(not isinstance(i, str) or not i for i in items)):
            raise PolicyPayrollError("PAYROLL_POLICY_INVALID", "必须明确人员依据、来源依赖和工资项清单")
        if cfg.get("taxMethod") != "RESIDENT_WAGE" or not str(cfg.get("withholdingAgent") or "").strip():
            raise PolicyPayrollError("PAYROLL_TAX_METHOD_UNSUPPORTED", "当前支持居民工资及合规全年奖，必须明确扣缴主体；其他税目不能套算")
        for key in ("supplementItemCodes", "bonusItemCodes"):
            extra = cfg.get(key, [])
            if not isinstance(extra, list) or len(extra) != len(set(extra)) or any(not isinstance(x, str) or not x for x in extra):
                raise PolicyPayrollError("PAYROLL_POLICY_INVALID", "补发及奖金项目须为明确且不重复的清单")
        if cfg.get("bonusItemCodes") and cfg.get("bonusTaxMethod") not in {"RESIDENT_WAGE", "ANNUAL_BONUS_SEPARATE"}:
            raise PolicyPayrollError("PAYROLL_BONUS_METHOD_REQUIRED", "奖金须明确并入综合所得或符合资格的单独计税")
        mode, codes = cfg.get("statutoryMode"), cfg.get("statutoryCodes")
        if mode not in {"REQUIRED", "NOT_APPLICABLE"} or not isinstance(codes, list) or len(codes) != len(set(codes)):
            raise PolicyPayrollError("PAYROLL_STATUTORY_SCOPE_REQUIRED", "须明确参保适用性与险种")
        if (mode == "REQUIRED" and not codes) or (mode == "NOT_APPLICABLE" and (codes or not cfg.get("statutoryReason"))):
            raise PolicyPayrollError("PAYROLL_STATUTORY_SCOPE_REQUIRED", "不适用须有依据；适用须列出险种，不能缺数视为豁免")

    @transaction.atomic
    def publish(self, kind, object_id):
        kind = str(kind).upper()
        model = MODELS.get(kind)
        if not model:
            raise PolicyPayrollError("PAYROLL_CONFIGURATION_KIND_INVALID", "配置类型不合法")
        obj = model.objects.filter(tenant_id=self.tenant_id, id=object_id).first()
        if obj is None:
            raise PolicyPayrollError("PAYROLL_CONFIGURATION_NOT_FOUND", "本校配置不存在")
        self._scope(self._key(kind, obj))
        obj = model.objects.select_for_update().get(id=obj.id, tenant_id=self.tenant_id)
        if obj.status == "PUBLISHED":
            verify_configuration(obj); return obj
        if obj.status != "DRAFT":
            raise PolicyPayrollError("PAYROLL_CONFIGURATION_STATE_INVALID", "仅待复核配置可以发布")
        if obj.created_by is None or obj.created_by == self.actor:
            raise PolicyPayrollError("PAYROLL_SEPARATION_OF_DUTIES", "经办与复核必须为不同认证人员")
        if kind == "POLICY":
            self._validate_policy(obj)
        peers = self._peers(kind, obj).filter(status="PUBLISHED")
        ancestors = set()
        parent_id = getattr(obj, "supersedes_id", None)
        while parent_id:
            parent = peers.filter(id=parent_id).first()
            if not parent or str(parent_id) in ancestors:
                raise PolicyPayrollError("PAYROLL_POLICY_CHAIN_INVALID", "替代对象必须为同一作用域的已发布前版")
            if parent.effective_from > obj.effective_from or (parent.effective_to and (not obj.effective_to or obj.effective_to > parent.effective_to)):
                raise PolicyPayrollError("PAYROLL_POLICY_REPLACEMENT_RANGE", "替代区间须在前版有效范围内；其他范围另建记录")
            ancestors.add(str(parent_id)); parent_id = getattr(parent, "supersedes_id", None)
        overlap = peers.filter(Q(effective_to__isnull=True) | Q(effective_to__gt=obj.effective_from))
        if obj.effective_to:
            overlap = overlap.filter(effective_from__lt=obj.effective_to)
        if any(str(item.id) not in ancestors for item in overlap):
            raise PolicyPayrollError("PAYROLL_CONFIGURATION_OVERLAP", "存在重叠的已发布配置；须明确替代关系或修正区间")
        if kind == "WORKLOAD":
            # A period-scoped lock also serializes two lecturers publishing the same shared class.
            rows = PayrollWorkloadFact.objects.filter(tenant_id=self.tenant_id, payroll_period_id=obj.payroll_period_id,
                                                      workload_key=obj.workload_key, status="PUBLISHED")
            serialized=[record(row) for row in rows]
            dates={obj.effective_from}
            for row in serialized:
                for name in ("effective_from","effective_to"):
                    if row.get(name):
                        point=date.fromisoformat(row[name])
                        if point>=obj.effective_from and (obj.effective_to is None or point<obj.effective_to):dates.add(point)
            for point in dates:
                live=effective_rows(serialized,point)
                live=[row for row in live if str(row["id"]) not in ancestors]
                if any(decimal(row["units"]) != obj.units or decimal(row["coefficient"]) != obj.coefficient or row["variable_key"] != obj.variable_key for row in live):
                    raise PolicyPayrollError("PAYROLL_SHARED_WORKLOAD_MISMATCH", "同一课次的总工作量、系数和口径须一致")
                if sum((decimal(row["share"]) for row in live), decimal(0)) + obj.share > 1:
                    raise PolicyPayrollError("PAYROLL_SHARED_WORKLOAD_OVERALLOCATED", "同一课次/成果分担比例超过100%")
        obj.content_hash = digest(content_payload(obj))
        obj.status = "PUBLISHED"; obj.published_at = timezone.now(); obj.updated_by = self.actor
        if hasattr(obj, "published_by"):
            obj.published_by = self.actor
        obj.save()
        from horilla.hr_event_service import emit_registered_event
        emit_registered_event(tenant_id=self.tenant_id, event_name="hr.payroll.policy.published",
                              payload={"kind": kind, "id": str(obj.id), "contentHash": obj.content_hash,
                                       "actorId": self.actor, "evidenceRef": getattr(obj, "evidence_ref", "rule-formula")},
                              correlation_id=self.correlation_id)
        return obj
