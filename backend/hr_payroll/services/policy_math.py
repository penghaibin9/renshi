"""Bounded, deterministic payroll arithmetic. No eval, database I/O or policy defaults.

Amounts are decimal strings at the API boundary. School-specific rates and
standards are never embedded here. Tax tables implement the cited ordinary
resident wage / eligible annual-bonus methods only; other methods fail closed.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_DOWN, ROUND_HALF_EVEN, ROUND_HALF_UP, localcontext

ROUNDINGS = {"HALF_UP": ROUND_HALF_UP, "HALF_EVEN": ROUND_HALF_EVEN, "DOWN": ROUND_DOWN}
CENT = Decimal("0.01")
MAX_VALUE = Decimal("9999999999999999.99")
TAX_POLICY_REF = "STA-2018-61/ordinary-resident-wages; MOF-STA-2023-30/eligible-bonus"
TAX_SOURCE_URLS = (
    "https://fgk.chinatax.gov.cn/zcfgk/c100012/c5194838/content.html",
    "https://shanghai.chinatax.gov.cn/zcfw/zcfgk/grsds/202308/t468460.html",
)


class PolicyPayrollError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def decimal(value, label="金额") -> Decimal:
    if value is None or isinstance(value, (bool, float)):
        raise PolicyPayrollError("PAYROLL_VALUE_MISSING_OR_INVALID", f"{label}必须是明确的十进制数，缺失不等于零")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise PolicyPayrollError("PAYROLL_VALUE_INVALID", f"{label}不是有效数字") from exc
    if not number.is_finite() or abs(number) > MAX_VALUE:
        raise PolicyPayrollError("PAYROLL_VALUE_OUT_OF_RANGE", f"{label}超出可计算范围")
    return number


def money(value, rounding="HALF_UP") -> Decimal:
    if rounding not in ROUNDINGS:
        raise PolicyPayrollError("PAYROLL_ROUNDING_INVALID", "舍入方式未配置")
    return decimal(value).quantize(CENT, rounding=ROUNDINGS[rounding])


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":"), default=str).encode()).hexdigest()


def active(row, on: date) -> bool:
    start = date.fromisoformat(str(row["effective_from"]))
    end = date.fromisoformat(str(row["effective_to"])) if row.get("effective_to") else None
    return start <= on and (end is None or on < end)


def expression(node, *, variables, calculated, selectors, standards, on, depth=0, budget=None):
    budget = [0] if budget is None else budget
    budget[0] += 1
    if depth > 8 or budget[0] > 256 or not isinstance(node, dict):
        raise PolicyPayrollError("PAYROLL_FORMULA_TOO_COMPLEX", "工资公式过深或格式不合法")
    op = str(node.get("op", "")).upper()
    trace = {"operation": op}

    def val(key):
        if key in calculated:
            return decimal(calculated[key], str(key))
        if key not in variables:
            raise PolicyPayrollError("PAYROLL_INPUT_VALUE_MISSING", f"缺少已核定输入：{key}")
        return decimal(variables[key], str(key))

    def sub(child):
        return expression(child, variables=variables, calculated=calculated, selectors=selectors,
                          standards=standards, on=on, depth=depth + 1, budget=budget)[0]

    with localcontext() as ctx:
        ctx.prec = 38
        if op == "FIXED":
            result = decimal(node.get("amount"))
        elif op == "INPUT":
            key = node.get("key")
            if not isinstance(key, str) or not key:
                raise PolicyPayrollError("PAYROLL_FORMULA_INVALID", "输入项名称不能为空")
            result = val(key)
            trace.update(inputKey=key, inputValue=str(result))
        elif op == "PERCENT":
            base = val(node.get("base")); rate = decimal(node.get("rate"), "比例")
            result = base * rate
            trace.update(base=node.get("base"), baseAmount=str(base), rate=str(rate))
        elif op in {"SUM", "MULTIPLY"}:
            args = node.get("args")
            if not isinstance(args, list) or not 1 <= len(args) <= 64:
                raise PolicyPayrollError("PAYROLL_FORMULA_INVALID", f"{op}需要1至64个运算项")
            amounts = [sub(item) for item in args]
            result = sum(amounts, Decimal(0)) if op == "SUM" else Decimal(1)
            if op == "MULTIPLY":
                for amount in amounts:
                    result *= amount
            trace["components"] = [str(item) for item in amounts]
        elif op == "SUBTRACT":
            left, right = sub(node.get("left")), sub(node.get("right"))
            result = left - right; trace.update(left=str(left), right=str(right))
        elif op == "CLAMP":
            value = sub(node.get("value"))
            low, high = decimal(node.get("min")), decimal(node.get("max"))
            if low > high:
                raise PolicyPayrollError("PAYROLL_FORMULA_INVALID", "下限不能大于上限")
            result = min(max(value, low), high)
            trace.update(unclamped=str(value), minimum=str(low), maximum=str(high))
        elif op == "CONDITIONAL":
            when = node.get("when")
            if not isinstance(when, dict) or when.get("key") not in selectors:
                raise PolicyPayrollError("PAYROLL_CONDITION_MISSING", "缺少条件判断所需的核定分类")
            operator = when.get("operator", "EQ")
            if operator not in {"EQ", "NE"}:
                raise PolicyPayrollError("PAYROLL_CONDITION_INVALID", "分类条件只支持明确的等于/不等于")
            match = str(selectors[when["key"]]) == str(when.get("value"))
            if operator == "NE":
                match = not match
            result = sub(node.get("then") if match else node.get("else"))
            trace.update(condition=when, matched=match)
        elif op == "LOOKUP":
            selector_key = node.get("selectorKey")
            if selector_key not in selectors or selectors[selector_key] in (None, ""):
                raise PolicyPayrollError("PAYROLL_GRADE_MISSING", f"缺少核定等级：{selector_key}")
            rows = [row for row in standards if row["table_code"] == node.get("tableCode")
                    and str(row["level_code"]) == str(selectors[selector_key]) and active(row, on)]
            if len(rows) != 1:
                raise PolicyPayrollError("PAYROLL_STANDARD_MISSING_OR_OVERLAP",
                                         f"{node.get('tableCode')}/{selectors[selector_key]}必须唯一命中有效标准")
            row = rows[0]; result = decimal(row["amount"])
            trace.update(standardId=row["id"], standardHash=row["content_hash"],
                         policyReference=row["evidence_ref"], tableCode=row["table_code"],
                         levelCode=row["level_code"])
        else:
            raise PolicyPayrollError("PAYROLL_FORMULA_UNSUPPORTED", f"不支持的公式：{op}")
    result = decimal(result, "公式结果")
    trace["unroundedAmount"] = str(result)
    return result, trace


def ordered_rules(rules):
    by_code = {}
    for rule in rules:
        code = rule["item_code"]
        if code in by_code:
            raise PolicyPayrollError("PAYROLL_RULE_OVERLAP", f"工资项 {code} 同时命中多条规则")
        by_code[code] = rule
    result, visiting, done = [], set(), set()

    def visit(code):
        if code in visiting:
            raise PolicyPayrollError("PAYROLL_FORMULA_CYCLE", "工资公式循环依赖")
        if code in done:
            return
        if code not in by_code:
            raise PolicyPayrollError("PAYROLL_RULE_DEPENDENCY_MISSING", f"缺少工资项：{code}")
        visiting.add(code)
        for key in by_code[code].get("dependencies_json", []):
            visit(key)
        visiting.remove(code); done.add(code); result.append(by_code[code])
    for code in sorted(by_code, key=lambda k: (by_code[k].get("priority", 100), k)):
        visit(code)
    return result


def evaluate_segment(rules, variables, selectors, standards, on):
    calculated, output = {}, []
    for rule in ordered_rules(rules):
        formula = dict(rule["formula_json"])
        if formula.get("op", "").upper() == "SUM" and "args" not in formula:
            formula["args"] = [{"op": "INPUT", "key": key} for key in rule.get("dependencies_json", [])]
        amount, explanation = expression(formula, variables=variables, calculated=calculated,
                                         selectors=selectors, standards=standards, on=on)
        if amount < 0 and not formula.get("allowNegative", False):
            raise PolicyPayrollError("PAYROLL_NEGATIVE_ITEM_REQUIRES_POLICY",
                                     f"{rule['item_code']}计算为负，须有明确补扣依据，不能自动扣款")
        calculated[rule["item_code"]] = amount
        output.append({"rule": rule, "raw": amount, "explanation": explanation})
    return output


# Cumulative wage table. Bonus uses the monthly conversion, not annual quick deductions.
ANNUAL_TABLE = (("36000", ".03", "0"), ("144000", ".10", "2520"),
                ("300000", ".20", "16920"), ("420000", ".25", "31920"),
                ("660000", ".30", "52920"), ("960000", ".35", "85920"),
                (None, ".45", "181920"))
BONUS_TABLE = (("3000", ".03", "0"), ("12000", ".10", "210"),
               ("25000", ".20", "1410"), ("35000", ".25", "2660"),
               ("55000", ".30", "4410"), ("80000", ".35", "7160"),
               (None, ".45", "15160"))


def bracket(amount, table):
    for ceiling, rate, quick in table:
        if ceiling is None or amount <= Decimal(ceiling):
            return Decimal(rate), Decimal(quick)
    raise AssertionError("unreachable bracket")


def resident_wage_tax(*, ytd_income, ytd_exempt, ytd_expense, ytd_special,
                      ytd_additional, ytd_other, ytd_relief, withheld):
    values = [decimal(v) for v in (ytd_income, ytd_exempt, ytd_expense, ytd_special,
                                    ytd_additional, ytd_other, ytd_relief, withheld)]
    if any(v < 0 for v in values):
        raise PolicyPayrollError("PAYROLL_TAX_INPUT_INVALID", "累计收入、扣除、减免和已扣税不能为负")
    income, exempt, expense, special, additional, other, relief, paid = values
    taxable = max(Decimal(0), income - exempt - expense - special - additional - other)
    rate, quick = bracket(taxable, ANNUAL_TABLE)
    cumulative = max(Decimal(0), money(taxable * rate - quick - relief))
    return {"taxableYtd": str(money(taxable)), "rate": str(rate), "quickDeduction": str(quick),
            "taxDueYtd": str(cumulative), "withheldBefore": str(paid),
            "withholding": str(max(Decimal("0.00"), cumulative - paid)),
            "refundDeferred": str(max(Decimal("0.00"), paid - cumulative)),
            "policyRef": TAX_POLICY_REF}


def annual_bonus_tax(amount, *, payment_date: date, eligible: bool, already_used: bool):
    if not eligible or already_used:
        raise PolicyPayrollError("PAYROLL_BONUS_NOT_ELIGIBLE", "未确认奖金资格或本年已使用单独计税")
    if not date(2019, 1, 1) <= payment_date <= date(2027, 12, 31):
        raise PolicyPayrollError("PAYROLL_BONUS_POLICY_EXPIRED", "当前日期不在已核验奖金政策有效期内")
    amount = decimal(amount)
    if amount <= 0:
        raise PolicyPayrollError("PAYROLL_BONUS_AMOUNT_INVALID", "奖金必须为正金额")
    rate, quick = bracket(amount / Decimal(12), BONUS_TABLE)
    return {"withholding": str(money(amount * rate - quick)), "rate": str(rate),
            "quickDeduction": str(quick), "policyRef": TAX_POLICY_REF}


def allocate_cost(total, shares):
    """Allocate integer cents by largest remainder; deterministic tie by cost code."""
    total = money(total)
    if not isinstance(shares, dict) or not shares:
        raise PolicyPayrollError("PAYROLL_COST_SHARES_MISSING", "经费分摊比例不能为空")
    parts = {str(k): decimal(v, "分摊比例") for k, v in shares.items()}
    if any(not k or v < 0 or v > 1 for k, v in parts.items()) or sum(parts.values()) != 1:
        raise PolicyPayrollError("PAYROLL_COST_SHARES_INVALID", "经费比例必须合计为1，且每项在0至1之间")
    cents = int(abs(total) * 100)
    exact = {key: Decimal(cents) * value for key, value in parts.items()}
    whole = {key: int(value) for key, value in exact.items()}
    remaining = cents - sum(whole.values())
    for key in sorted(parts, key=lambda k: (-(exact[k] - whole[k]), k))[:remaining]:
        whole[key] += 1
    sign = 1 if total >= 0 else -1
    return {key: str((Decimal(sign * value) / 100).quantize(CENT)) for key, value in sorted(whole.items())}


def validate_formula_definition(formula, depth=0):
    """Validate configuration before publication, without executing arbitrary code."""
    if depth > 8 or not isinstance(formula, dict):
        raise PolicyPayrollError("PAYROLL_FORMULA_INVALID", "公式必须为有限深度的结构化对象")
    op = str(formula.get("op", "")).upper()
    def required_text(key):
        value = formula.get(key)
        if not isinstance(value, str) or not value.strip() or len(value) > 64:
            raise PolicyPayrollError("PAYROLL_FORMULA_INVALID", f"公式缺少 {key}")
    if op == "FIXED":
        decimal(formula.get("amount"))
    elif op == "INPUT":
        required_text("key")
    elif op == "PERCENT":
        required_text("base"); decimal(formula.get("rate"))
    elif op in {"MULTIPLY", "SUM"}:
        args = formula.get("args", [])
        if op == "MULTIPLY" and not args:
            raise PolicyPayrollError("PAYROLL_FORMULA_INVALID", "乘积需要运算项")
        if not isinstance(args, list) or len(args) > 64:
            raise PolicyPayrollError("PAYROLL_FORMULA_INVALID", "运算项必须为有限列表")
        for arg in args:
            validate_formula_definition(arg, depth + 1)
    elif op == "LOOKUP":
        required_text("tableCode"); required_text("selectorKey")
    elif op == "SUBTRACT":
        for key in ("left", "right"):
            validate_formula_definition(formula.get(key), depth + 1)
    elif op == "CLAMP":
        validate_formula_definition(formula.get("value"), depth + 1)
        if decimal(formula.get("min")) > decimal(formula.get("max")):
            raise PolicyPayrollError("PAYROLL_FORMULA_INVALID", "公式上下限颠倒")
    elif op == "CONDITIONAL":
        when = formula.get("when")
        if (not isinstance(when, dict) or not isinstance(when.get("key"), str)
                or "value" not in when or when.get("operator", "EQ") not in {"EQ", "NE"}):
            raise PolicyPayrollError("PAYROLL_FORMULA_INVALID", "条件结构不合法")
        validate_formula_definition(formula.get("then"), depth + 1)
        validate_formula_definition(formula.get("else"), depth + 1)
    else:
        raise PolicyPayrollError("PAYROLL_FORMULA_UNSUPPORTED", f"不支持的运算 {op}")
