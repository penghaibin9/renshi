"""Pure, versioned national flexible-retirement checks (no database dependencies).

Sources (verified 2026-09-14): 人社部发〔2024〕94号, articles 1,2,4,6,7,8,11;
NPC decision on gradual retirement, effective 2025-01-01. School-specific or
special-category rules must be reviewed separately; this is not a pension award.
"""
from calendar import monthrange
from datetime import date

RULE_VERSION = "CN-FLEX-2025-94/2026-09-14"
CAPACITIES = frozenset({"PUBLIC_TECHNICAL", "PUBLIC_OTHER", "PUBLIC_LEADER",
    "PUBLIC_MANAGEMENT", "CIVIL_SERVANT", "PRIVATE_EMPLOYEE"})
DELAY_EXCLUDED = frozenset({"PUBLIC_LEADER", "PUBLIC_MANAGEMENT", "CIVIL_SERVANT"})


class FlexRuleError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def add_months(day: date, months: int) -> date:
    if type(day) is not date or type(months) is not int:
        raise FlexRuleError("FLEX_DATE_INVALID", "日期或月份无效")
    year, month = divmod(day.year * 12 + day.month - 1 + months, 12)
    if not 1 <= year <= 9999:
        raise FlexRuleError("FLEX_DATE_INVALID", "日期超出范围")
    return date(year, month + 1, min(day.day, monthrange(year, month + 1)[1]))


def minimum_contribution_months(year: int) -> int:
    if type(year) is not int or not 2025 <= year <= 9999:
        raise FlexRuleError("FLEX_YEAR_UNSUPPORTED", "本规则仅适用于2025年及以后")
    return min(240, 180 + max(0, year - 2029) * 6)


def validate_choice(*, mode, requested_date, statutory_date, original_minimum_date,
                    notice_date, today, parent_date=None):
    for day in (requested_date, statutory_date, original_minimum_date, notice_date, today):
        if type(day) is not date:
            raise FlexRuleError("FLEX_DATE_REQUIRED", "必须提供有效日期")
    if requested_date < date(2025, 1, 1) or notice_date > today:
        raise FlexRuleError("FLEX_DATE_INVALID", "退休时间不得早于2025年，告知日期不得晚于今天")
    if requested_date < today:
        raise FlexRuleError("FLEX_PAST_DATE_FORBIDDEN", "新申请或审批不得回填已经过去的退休日期")
    if mode == "EARLY":
        if not max(original_minimum_date, add_months(statutory_date, -36)) <= requested_date < statutory_date:
            raise FlexRuleError("FLEX_EARLY_RANGE", "提前退休不得超过3年，也不得低于原法定退休年龄")
        # Calendar months, never a hardcoded 90 days; compare from the notice.
        if add_months(notice_date, 3) > requested_date:
            raise FlexRuleError("FLEX_NOTICE_TOO_LATE", "弹性提前退休须至少提前3个月书面告知")
    elif mode == "DELAY":
        if not statutory_date < requested_date <= add_months(statutory_date, 36):
            raise FlexRuleError("FLEX_DELAY_RANGE", "延迟退休必须晚于法定日期，且不得超过3年")
        if add_months(notice_date, 1) > statutory_date:
            raise FlexRuleError("FLEX_AGREEMENT_TOO_LATE", "延迟退休须在法定退休前至少1个月书面约定")
    elif mode == "END_DELAY":
        if type(parent_date) is not date or not statutory_date <= requested_date < parent_date:
            raise FlexRuleError("FLEX_END_DELAY_RANGE", "终止延迟时间必须在法定退休后且早于原约定日期")
        if not statutory_date <= today < parent_date or requested_date < today:
            raise FlexRuleError("FLEX_END_DELAY_NOT_ACTIVE", "仅能在延迟退休期间协商终止，不能回填过去日期")
    else:
        raise FlexRuleError("FLEX_MODE_INVALID", "不支持的弹性退休类型")


def validate_approval(*, mode, requested_date, statutory_date, capacity,
                      contribution_months, agreement_date, today,
                      has_approval_evidence, has_contribution_evidence,
                      has_agreement_evidence):
    if mode not in {"EARLY", "DELAY", "END_DELAY"}:
        raise FlexRuleError("FLEX_MODE_INVALID", "不支持的退休模式")
    if any(type(day) is not date for day in (requested_date, statutory_date, today)):
        raise FlexRuleError("FLEX_DATE_REQUIRED", "须提供有效日期")
    if requested_date < today:
        raise FlexRuleError("FLEX_PAST_DATE_FORBIDDEN", "不能审批已经过去的退休日期")
    if capacity not in CAPACITIES:
        raise FlexRuleError("FLEX_CAPACITY_REQUIRED", "人事部门必须核定人员管理身份，不能由申请人自行决定")
    if mode in {"DELAY", "END_DELAY"} and capacity in DELAY_EXCLUDED:
        raise FlexRuleError("FLEX_DELAY_EXCLUDED", "公务员、国有企事业单位领导人员及其他管理人员不适用弹性延迟退休")
    if type(contribution_months) is not int or not 0 <= contribution_months <= 1200:
        raise FlexRuleError("FLEX_CONTRIBUTION_INVALID", "必须填写有证据支持的社保缴费月数；在校工龄不能替代缴费年限")
    year = requested_date.year if mode == "EARLY" else statutory_date.year
    required = minimum_contribution_months(year)
    if contribution_months < required:
        raise FlexRuleError("FLEX_CONTRIBUTION_INSUFFICIENT", f"该退休口径要求至少{required}个月缴费记录")
    if not has_approval_evidence or not has_contribution_evidence:
        raise FlexRuleError("FLEX_REVIEW_EVIDENCE_REQUIRED", "须提供人事审批依据和社保缴费核验材料")
    if mode in {"DELAY", "END_DELAY"}:
        if type(agreement_date) is not date or not has_agreement_evidence:
            raise FlexRuleError("FLEX_AGREEMENT_REQUIRED", "须提供单位与本人书面协商一致的材料和签署日期")
        if agreement_date > today:
            raise FlexRuleError("FLEX_AGREEMENT_DATE_INVALID", "协议不能签署于未来")
        if mode == "DELAY" and add_months(agreement_date, 1) > statutory_date:
            raise FlexRuleError("FLEX_AGREEMENT_TOO_LATE", "书面协议须在法定退休日期前至少1个月签署")
        if mode == "END_DELAY" and not statutory_date <= agreement_date <= requested_date:
            raise FlexRuleError("FLEX_AGREEMENT_DATE_INVALID", "终止延迟协议应在延迟期间、拟退休日期之前签署")
    return {"ruleVersion": RULE_VERSION, "contributionYear": year,
            "requiredContributionMonths": required, "verifiedContributionMonths": contribution_months}
