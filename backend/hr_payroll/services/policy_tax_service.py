"""Serialized payroll tax reservations; balances advance only on verified settlement.

A trial is not a payment and never changes tax totals. One pending result per
withholding-agent/person/year prevents a second payroll depending on unpaid tax.
"""
from __future__ import annotations
from datetime import date
from django.db import transaction
from hr_payroll.policy_models import PayrollTaxAccount, PayrollTaxReservation
from .policy_math import PolicyPayrollError, annual_bonus_tax, decimal, digest, resident_wage_tax


class PolicyTaxService:
    def __init__(self, tenant_id, actor_user_id=None):
        if not tenant_id or int(tenant_id) <= 0:
            raise PolicyPayrollError("TENANT_CONTEXT_REQUIRED", "学校上下文缺失")
        self.tenant = int(tenant_id); self.actor = actor_user_id

    def _identity(self, data):
        try:
            from uuid import UUID
            day = date.fromisoformat(str(data["paymentDate"]))
            person = UUID(str(data["personId"]))
            agent = str(data["withholdingAgent"]).strip()
        except (ValueError, KeyError, TypeError) as exc:
            raise PolicyPayrollError("PAYROLL_TAX_IDENTITY_INVALID", "扣缴主体、自然人或支付日期无效") from exc
        if not agent or len(agent) > 64:
            raise PolicyPayrollError("PAYROLL_TAX_AGENT_REQUIRED", "扣缴义务人必须明确")
        return dict(tenant_id=self.tenant, withholding_agent_code=agent, person_id=person, tax_year=day.year)

    def _opening(self, data):
        deductions = data.get("deductions") or {}
        opening = deductions.get("openingBalance")
        if not isinstance(opening, dict) or not deductions.get("openingEvidenceRef"):
            raise PolicyPayrollError("PAYROLL_TAX_OPENING_REQUIRED", "首次使用须核对年初至今税账；无历史收入也必须明确确认零余额，不能默认清零")
        day = date.fromisoformat(str(data["paymentDate"]))
        try:
            as_of = date.fromisoformat(str(opening["asOfDate"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise PolicyPayrollError("PAYROLL_TAX_OPENING_DATE_REQUIRED", "期初累计需注明截至日期") from exc
        if as_of >= day or as_of < date(day.year - 1, 12, 31):
            raise PolicyPayrollError("PAYROLL_TAX_OPENING_DATE_INVALID", "期初累计须从本税年承接，且截至日早于本次支付")
        result = {key: str(decimal(opening.get(key), key)) for key in ("income", "exempt", "withheld")}
        if any(decimal(x) < 0 for x in result.values()) or decimal(result["exempt"]) > decimal(result["income"]):
            raise PolicyPayrollError("PAYROLL_TAX_OPENING_INVALID", "累计收入、免税、已扣税须为有效非负金额")
        old_deductions = opening.get("deductions")
        if not isinstance(old_deductions, dict):
            raise PolicyPayrollError("PAYROLL_TAX_OPENING_INVALID", "期初累计扣除不完整")
        result["deductions"] = {key: str(decimal(old_deductions.get(key), key)) for key in ("expenseYtd", "specialYtd", "additionalYtd", "otherYtd", "reliefYtd")}
        if any(decimal(x) < 0 for x in result["deductions"].values()) or not isinstance(opening.get("bonusUsed"), bool):
            raise PolicyPayrollError("PAYROLL_TAX_OPENING_INVALID", "期初扣除或奖金使用情况未核实")
        result["bonusUsed"] = opening["bonusUsed"]
        result["openingEvidenceRef"] = str(deductions["openingEvidenceRef"])
        result["openingAsOfDate"] = str(as_of)
        return result

    def quote(self, data, *, account=None, for_result_id=None):
        identity = self._identity(data)
        if account is None:
            account = PayrollTaxAccount.objects.filter(**identity).first()
        if account and account.pending_result_id and str(account.pending_result_id) != str(for_result_id):
            raise PolicyPayrollError("PAYROLL_TAX_PENDING_SETTLEMENT", "同一扣缴主体下该人员有未确定结算的工资，先查询原回执，不重复算税发薪")
        totals = account.totals_json if account and account.totals_json else self._opening(data)
        version = account.version_no if account else 0
        day = date.fromisoformat(str(data["paymentDate"]))
        if account and account.last_payment_date and day < account.last_payment_date:
            raise PolicyPayrollError("PAYROLL_TAX_PAYMENT_ORDER", "实际支付期早于已确认税账；请走税务更正，不回写历史累计")
        income, exempt = decimal(data.get("income")), decimal(data.get("exemptIncome", "0"))
        if income < 0 or exempt < 0 or exempt > income:
            raise PolicyPayrollError("PAYROLL_TAX_INCOME_INVALID", "普通支付收入及免税额须非负，负差额另走核定抵扣或更正")
        method = data.get("method")
        deductions = data.get("deductions")
        if not isinstance(deductions, dict) or not deductions.get("evidenceRef"):
            raise PolicyPayrollError("PAYROLL_TAX_DEDUCTION_EVIDENCE_REQUIRED", "累计扣除必须由已复核税务资料提供")
        if deductions.get("paymentMonth") != day.strftime("%Y-%m"):
            raise PolicyPayrollError("PAYROLL_TAX_DEDUCTION_PERIOD_MISMATCH", "扣除资料不属于本次支付月份")
        if deductions.get("residentConfirmed") is not True:
            raise PolicyPayrollError("PAYROLL_TAX_RESIDENCY_REQUIRED", "须明确确认为居民个人，不能按人员标签猜测税目")
        after = dict(totals)
        if method == "RESIDENT_WAGE":
            keys = ("expenseYtd", "specialYtd", "additionalYtd", "otherYtd", "reliefYtd")
            values = {key: decimal(deductions.get(key), key) for key in keys}
            if any(value < 0 for value in values.values()):
                raise PolicyPayrollError("PAYROLL_TAX_DEDUCTION_INVALID", "累计扣除不可为负")
            mode = deductions.get("deductionMode")
            if mode == "ORDINARY":
                months = deductions.get("employmentMonths")
                if isinstance(months, bool) or not isinstance(months, int) or not 1 <= months <= day.month:
                    raise PolicyPayrollError("PAYROLL_TAX_EMPLOYMENT_MONTHS_INVALID", "普通累计减除费用须有当年任职受雇月份数")
                if values["expenseYtd"] != decimal(months) * 5000:
                    raise PolicyPayrollError("PAYROLL_TAX_EXPENSE_MISMATCH", "普通累计减除费用须与已确认任职月份一致")
            elif mode != "EXTERNALLY_CONFIRMED_SPECIAL":
                raise PolicyPayrollError("PAYROLL_TAX_DEDUCTION_MODE_REQUIRED", "必须明确普通或已由税务资料核定的特殊扣除方式")
            if values["expenseYtd"] > 60000:
                raise PolicyPayrollError("PAYROLL_TAX_EXPENSE_OUT_OF_RANGE", "年度减除费用超出当前支持范围，须专项核对")
            previous = totals.get("deductions", {})
            if any(value < decimal(previous.get(key, "0")) for key, value in values.items()):
                raise PolicyPayrollError("PAYROLL_TAX_CORRECTION_REQUIRED", "累计扣除比已结算记录减少，须核实更正，不能静默覆盖")
            accumulated_income = decimal(totals.get("income", "0")) + income
            accumulated_exempt = decimal(totals.get("exempt", "0")) + exempt
            result = resident_wage_tax(ytd_income=accumulated_income, ytd_exempt=accumulated_exempt,
                                       ytd_expense=values["expenseYtd"], ytd_special=values["specialYtd"],
                                       ytd_additional=values["additionalYtd"], ytd_other=values["otherYtd"],
                                       ytd_relief=values["reliefYtd"], withheld=totals.get("withheld", "0"))
            after.update(income=str(accumulated_income), exempt=str(accumulated_exempt),
                         withheld=str(decimal(totals.get("withheld", "0")) + decimal(result["withholding"])),
                         deductions={key: str(value) for key, value in values.items()})
        elif method == "ANNUAL_BONUS_SEPARATE":
            if exempt:
                raise PolicyPayrollError("PAYROLL_BONUS_EXEMPT_UNSUPPORTED", "奖金免税额须专项核对，不套普通奖金公式")
            if deductions.get("bonusUsedElsewhere") is not False:
                raise PolicyPayrollError("PAYROLL_BONUS_USAGE_CONFIRMATION_REQUIRED", "须核对当年其他扣缴单位是否已使用一次性奖金单独计税")
            result = annual_bonus_tax(income, payment_date=day,
                                      eligible=deductions.get("bonusEligible") is True,
                                      already_used=bool(totals.get("bonusUsed")))
            after.update(bonusUsed=True, bonusIncome=str(income), bonusWithheld=result["withholding"])
        else:
            raise PolicyPayrollError("PAYROLL_TAX_METHOD_UNSUPPORTED", "该税目未实现，不以工资累计法替代")
        return {**result, "accountVersion": version, "accountBeforeHash": digest(totals),
                "totalsAfter": after, "paymentDate": str(day), "method": method,
                "withholdingAgent": identity["withholding_agent_code"], "personId": str(identity["person_id"])}

    @transaction.atomic
    def reserve(self, *, result, data, approved_quote):
        if int(result.tenant_id) != self.tenant:
            raise PolicyPayrollError("TENANT_SCOPE_MISMATCH", "工资结果不属于本校")
        prior = PayrollTaxReservation.objects.filter(tenant_id=self.tenant, payroll_result_id=result.id).first()
        if prior:
            if prior.input_json != data or prior.quote_json != approved_quote:
                raise PolicyPayrollError("PAYROLL_TAX_IDEMPOTENCY_CONFLICT", "该工资结果已有不同计税依据")
            return prior
        identity = self._identity(data)
        account = PayrollTaxAccount.objects.filter(**identity).first()
        if account is None:
            account, _ = PayrollTaxAccount.objects.get_or_create(**identity, defaults={"totals_json": self._opening(data), "created_by": self.actor})
        account = PayrollTaxAccount.objects.select_for_update().get(pk=account.pk, tenant_id=self.tenant)
        quote = self.quote(data, account=account, for_result_id=result.id)
        if quote != approved_quote:
            raise PolicyPayrollError("PAYROLL_TAX_LEDGER_CHANGED", "税账在试算复核后变化，请重新试算复核，不能悄悄改变实发金额")
        reservation = PayrollTaxReservation.objects.create(
            tenant_id=self.tenant, created_by=self.actor, updated_by=self.actor, payroll_result_id=result.id,
            tax_account_id=account.id, staff_id=result.staff_id, input_json=data, quote_json=quote,
            content_hash=digest({"input": data, "quote": quote}), status="RESERVED")
        account.pending_result_id = result.id; account.updated_by = self.actor
        account.save(update_fields=["pending_result_id", "updated_by", "updated_at"])
        return reservation

    @transaction.atomic
    def post_verified_receipt(self, instruction, receipt):
        reservation = PayrollTaxReservation.objects.select_for_update().filter(
            tenant_id=self.tenant, payroll_result_id=instruction.payroll_result_id).first()
        if reservation is None:
            return None  # Legacy calculations have no policy-tax reservation.
        if reservation.content_hash != digest({"input": reservation.input_json, "quote": reservation.quote_json}):
            raise PolicyPayrollError("PAYROLL_TAX_EVIDENCE_INVALID", "税额依据校验失败")
        if reservation.status == "POSTED":
            if reservation.receipt_ref != str(receipt.get("receiptNo")):
                raise PolicyPayrollError("PAYROLL_TAX_RECEIPT_CONFLICT", "已入账税额对应不同回执")
            return reservation
        if receipt.get("status") != "ACCEPTED":
            # A rejection does not erase the reservation: an authorized retry must retain tax context.
            return reservation
        if decimal(receipt.get("settledAmount")) != instruction.requested_amount:
            raise PolicyPayrollError("PAYROLL_TAX_SETTLEMENT_AMOUNT_MISMATCH", "回执金额与工资指令不同")
        actual = receipt.get("paidDate")
        try:
            actual_day = date.fromisoformat(str(actual))
        except ValueError:
            actual_day = None
        if actual_day is None or str(actual_day)[:7] != reservation.input_json["paymentDate"][:7]:
            # Keep the bank's real accepted fact; do not fabricate a tax payment month.
            reservation.status = "DATE_REVIEW"; reservation.receipt_ref = str(receipt.get("receiptNo"))
            reservation.updated_by = self.actor
            reservation.save(update_fields=["status", "receipt_ref", "updated_by", "updated_at"])
            return reservation
        account = PayrollTaxAccount.objects.select_for_update().get(id=reservation.tax_account_id, tenant_id=self.tenant)
        quote = reservation.quote_json
        if (str(account.pending_result_id) != str(instruction.payroll_result_id)
                or account.version_no != quote["accountVersion"] or digest(account.totals_json or {}) != quote["accountBeforeHash"]):
            raise PolicyPayrollError("PAYROLL_TAX_LEDGER_CONFLICT", "税账锁定版本不一致，保留待处理状态")
        account.totals_json = quote["totalsAfter"]
        account.version_no += 1; account.pending_result_id = None
        account.last_payment_date = max(filter(None, [actual_day, account.last_payment_date]))
        account.updated_by = self.actor
        account.save(update_fields=["totals_json", "version_no", "pending_result_id", "last_payment_date", "updated_by", "updated_at"])
        reservation.status = "POSTED"; reservation.receipt_ref = str(receipt["receiptNo"]); reservation.updated_by = self.actor
        reservation.save(update_fields=["status", "receipt_ref", "updated_by", "updated_at"])
        return reservation

    @transaction.atomic
    def supplement_verified_date(self, *, instruction_id, provider_payload):
        """Trusted worker only. Verify a fresh provider proof, never trust a typed date."""
        from hr_payroll.calculation_models import PayrollPaymentInstruction
        from hr_payroll.policy_models import PayrollTaxReceiptSupplement
        from .payment_provider_registry import PaymentProviderRegistry
        from .payment_service import PayrollPaymentService
        instruction=PayrollPaymentInstruction.objects.select_for_update().filter(tenant_id=self.tenant,id=instruction_id).first()
        if not instruction or instruction.status!="ACCEPTED":
            raise PolicyPayrollError("PAYROLL_TAX_PAYMENT_NOT_ACCEPTED","须有已认证的付款成功记录")
        original=(instruction.provider_receipt_json or {}).get("receipt") or {}
        verified=PaymentProviderRegistry.resolve(instruction.provider_code).verify_receipt(provider_payload)
        receipt=PayrollPaymentService(self.tenant,self.actor)._normalize_provider_receipt(instruction,verified)
        for key in ("tenantId","instructionId","instructionNo","providerCode","currencyCode","idempotencyKey","receiptNo","status","settledAmount"):
            if str(original.get(key))!=str(receipt.get(key)):
                raise PolicyPayrollError("PAYROLL_TAX_PROOF_CONFLICT","补充凭据必须对应原笔已付款事实")
        if not receipt.get("paidDate") or original.get("paidDate") and original["paidDate"]!=receipt["paidDate"]:
            raise PolicyPayrollError("PAYROLL_TAX_DATE_CORRECTION_REQUIRED","缺少实际支付日或与原回执冲突，不覆盖原记录")
        reservation=PayrollTaxReservation.objects.select_for_update().filter(tenant_id=self.tenant,payroll_result_id=instruction.payroll_result_id).first()
        if not reservation:raise PolicyPayrollError("PAYROLL_TAX_RESERVATION_NOT_FOUND","该工资没有制度税账预留")
        if receipt["paidDate"][:7]!=reservation.input_json["paymentDate"][:7]:
            raise PolicyPayrollError("PAYROLL_TAX_CROSS_MONTH_CORRECTION_REQUIRED","跨月实付须核对累计税务更正，不能仅补日期冒充已对账")
        proof=PayrollTaxReceiptSupplement.objects.filter(tenant_id=self.tenant,tax_reservation_id=reservation.id).first()
        if proof and (proof.receipt_json!=receipt or proof.content_hash!=digest(receipt)):
            raise PolicyPayrollError("PAYROLL_TAX_PROOF_CONFLICT","已存在不同的补充凭据")
        if not proof:
            PayrollTaxReceiptSupplement.objects.create(tenant_id=self.tenant,created_by=self.actor,updated_by=self.actor,
                tax_reservation_id=reservation.id,receipt_json=receipt,content_hash=digest(receipt))
        return self.post_verified_receipt(instruction,receipt)
