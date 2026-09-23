"""Approved, positive historical back-pay using frozen facts and current approved corrections.

No caller-provided amount is accepted. Original results remain unchanged. Negative
recoveries and statutory/tax-return corrections require an explicit settlement
workflow and are blocked rather than converted into a negative bank instruction.
"""
import copy
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from django.db import transaction
from django.db.models import Max
from django.utils import timezone
from hr_payroll.models import PayrollPeriod,PayrollProfile,PayrollResultFact
from hr_payroll.calculation_models import PayrollInputSnapshot,PayrollCalculationBatch,PayrollCalculationLine
from hr_payroll.policy_models import (PayrollTrial,PayrollTrialApproval,PayrollRetroApplication,
    PayrollBasisVersion,PayrollStandardVersion,PayrollWorkloadFact,PayrollTaxReservation)
from .policy_payroll_service import (PolicyPayrollService,SCHEMA,compute_earnings,jsonable,
    verify_policy_snapshot,verify_trial,trial_digest,_one)
from .policy_configuration_service import record,effective_rows
from .policy_math import PolicyPayrollError,digest,decimal,money,allocate_cost,active
from .policy_tax_service import PolicyTaxService
from .calculation_service import verify_payroll_result_input_evidence,PayrollCalculationService
from .adjustment_service import PayrollAdjustmentService


class PolicyRetroService(PolicyPayrollService):
    def _chain(self,source_id):
        source=PayrollResultFact.objects.select_for_update().filter(tenant_id=self.tenant,id=source_id).first()
        if not source or source.status not in {"FINALIZED","ADJUSTED"}:
            raise PolicyPayrollError("PAYROLL_RETRO_SOURCE_NOT_FOUND","须选本校已封账工资结果")
        if PayrollResultFact.objects.filter(tenant_id=self.tenant,supersedes_result_id=source.id).exists():
            raise PolicyPayrollError("PAYROLL_RETRO_SOURCE_SUPERSEDED","该结果已有后续补差，请选最新链尾")
        chain=[];seen=set();node=source
        while node:
            if node.id in seen or node.staff_id!=source.staff_id or node.payroll_period_id!=source.payroll_period_id or node.currency_code!="CNY":
                raise PolicyPayrollError("PAYROLL_RETRO_CHAIN_INVALID","历史工资链循环或归属不一致")
            seen.add(node.id)
            snapshot=verify_payroll_result_input_evidence(node);trial=verify_policy_snapshot(snapshot)
            reservation=PayrollTaxReservation.objects.filter(tenant_id=self.tenant,payroll_result_id=node.id,status="POSTED").first()
            if not reservation:
                raise PolicyPayrollError("PAYROLL_RETRO_UNSETTLED_SOURCE","须先核实原工资支付及税账，不能对未结算工资再补发")
            chain.append((node,trial))
            if not node.supersedes_result_id:break
            node=PayrollResultFact.objects.filter(tenant_id=self.tenant,id=node.supersedes_result_id).first()
            if node is None:raise PolicyPayrollError("PAYROLL_RETRO_CHAIN_MISSING","历史工资链缺少前驱")
        if chain[-1][0].status!="FINALIZED" or chain[-1][1].purpose!="NORMAL":
            raise PolicyPayrollError("PAYROLL_RETRO_ROOT_INVALID","须有制度核算的正式原始工资")
        proof=[{"id":str(n.id),"gross":str(n.gross_amount),"deduction":str(n.deduction_amount),"net":str(n.net_amount),"trialHash":t.content_hash} for n,t in chain]
        return source,chain,digest(proof)

    def _corrected(self,original):
        from .compensation_change_service import CompensationChangeService
        payload=copy.deepcopy(original)
        profiles={s["profileId"] for s in payload["segments"] if not s.get("unpaidOutsideRelationship")}
        groups={s["payGroupCode"] for s in payload["segments"] if not s.get("unpaidOutsideRelationship")}
        bases=self._published(PayrollBasisVersion,staff_id=payload["staffId"],payroll_profile_id__in=profiles)
        standards=self._published(PayrollStandardVersion,pay_group_code__in=groups)
        workloads=self._published(PayrollWorkloadFact,payroll_period_id=payload["periodId"],staff_id=payload["staffId"])
        first=date.fromisoformat(payload["startDate"]);last=date.fromisoformat(payload["endDate"])
        service=CompensationChangeService(self.tenant,actor_user_id=self.actor)
        changes=service.effective_cases(staff_id=payload["staffId"],period_start=first,period_end=last)
        new=[]
        for old in payload["segments"]:
            if old.get("unpaidOutsideRelationship"):
                new.append(old);continue
            a=date.fromisoformat(old["from"]);b=date.fromisoformat(old["toExclusive"])
            bounds={a,b}
            for row in bases+standards:
                for key in ("effective_from","effective_to"):
                    d=date.fromisoformat(row[key]) if row.get(key) else None
                    if d and a<d<b:bounds.add(d)
            for row in changes:
                for d in (row.effective_from,row.effective_to+timedelta(days=1) if row.effective_to else None):
                    if d and a<d<b:bounds.add(d)
            points=sorted(bounds)
            for start,stop in zip(points,points[1:]):
                segment=copy.deepcopy(old)
                basis=_one(effective_rows([x for x in bases if x["payroll_profile_id"]==old["profileId"]],start),"PAYROLL_RETRO_BASIS_MISSING","更正后的核定")
                if basis["selectors_json"].get("employmentRelationshipId")!=old["selectors"].get("employmentRelationshipId"):
                    raise PolicyPayrollError("PAYROLL_RETRO_RELATION_CORRECTION_REQUIRED","任职关系更正须先专门核对，不用待遇补差改写历史人员关系")
                variables={}
                for authority,source in old["sources"].items():
                    if authority!="HR15_CHANGE":variables.update(source["variables"])
                variables.update(basis["variables_json"])
                work=effective_rows(workloads,last);values=defaultdict(Decimal)
                for row in work:values[row["variable_key"]]+=decimal(row["units"])*decimal(row["share"])*decimal(row["coefficient"])
                for key,val in values.items():
                    if key in variables:raise PolicyPayrollError("PAYROLL_WORKLOAD_VARIABLE_CONFLICT","工作量与核定输入重复")
                    variables[key]=str(val)
                segment["sources"].pop("HR15_CHANGE",None)
                if changes:
                    raw=service.payroll_input_source(staff_id=payload["staffId"],period_id=payload["periodId"],period_start=start,period_end=stop-timedelta(days=1),base_variables=variables)
                    if raw:
                        source,vals=PayrollCalculationService(self.tenant,actor_user_id=self.actor)._normalize_provider_result(authority="HR15_CHANGE",request={"periodId":payload["periodId"],"staffId":payload["staffId"]},raw=raw)
                        segment["sources"]["HR15_CHANGE"]=source;variables.update(vals)
                segment.update({"from":str(start),"toExclusive":str(stop),"variables":jsonable(variables),
                    "basisId":basis["id"],"basisHash":basis["content_hash"],"selectors":basis["selectors_json"],
                    "standards":effective_rows([x for x in standards if x["pay_group_code"]==old["payGroupCode"]],start),"verifiedWorkloads":work})
                new.append(segment)
        payload["segments"]=new
        return payload

    def build_retro(self,source_id,payment_date,payment_profile_id):
        source,chain,chain_hash=self._chain(source_id)
        original=chain[-1][1]
        period=self._period(source.payroll_period_id)
        if period.status not in {"FINALIZED","CLOSED"}:
            raise PolicyPayrollError("PAYROLL_RETRO_PERIOD_NOT_FINAL","原期间未封账")
        corrected=self._corrected(original.input_payload_json)
        payable=[x for x in corrected["segments"] if not x.get("unpaidOutsideRelationship")]
        statutory_now=self._statutory(period,payable)
        if statutory_now!=original.input_payload_json["statutory"]:
            raise PolicyPayrollError("PAYROLL_RETRO_STATUTORY_REVIEW_REQUIRED", "缴费标准或基数变化须专项重核，不静默遗漏社保补差")
        lines,gross,ded,employer=compute_earnings(corrected)
        old_lines,old_g,old_d,old_e=compute_earnings(original.input_payload_json)
        # Non-tax deductions/employer costs, especially statutory reassessments,
        # must not disappear inside a positive cash correction.
        if ded!=old_d or employer!=old_e:
            raise PolicyPayrollError("PAYROLL_RETRO_DEDUCTION_REVIEW_REQUIRED","扣款/单位成本变化需专项更正，不以普通补发掩盖")
        prior=sum((n.gross_amount for n,t in chain),Decimal(0))
        delta=money(gross-prior)
        if delta<=0:
            raise PolicyPayrollError("PAYROLL_RETRO_NO_POSITIVE_DELTA","无正向待补差额；负向追扣须办理经确认的债务/抵扣，不自动负数发薪")
        payment_date=date.fromisoformat(str(payment_date))
        profile=PayrollProfile.objects.filter(tenant_id=self.tenant,id=payment_profile_id,staff_id=source.staff_id).first()
        if not profile or not profile.payment_account_ref:
            raise PolicyPayrollError("PAYROLL_RETRO_PAYMENT_PROFILE_INVALID","请选择本人的有效收款身份及账户引用")
        bases=self._published(PayrollBasisVersion,payroll_profile_id=profile.id,staff_id=source.staff_id)
        basis=_one(effective_rows(bases,payment_date),"PAYROLL_RETRO_TAX_BASIS_REQUIRED","实际支付月份的税务核定")
        if payment_date<date.fromisoformat(original.input_payload_json["paymentDate"]):
            raise PolicyPayrollError("PAYROLL_RETRO_PAYMENT_DATE_INVALID","补发支付日不可早于原预计支付日")
        tax_input={"personId":original.input_payload_json["personId"],"withholdingAgent":original.input_payload_json["withholdingAgent"],
             "paymentDate":str(payment_date),"method":"RESIDENT_WAGE","income":str(delta),"exemptIncome":"0","deductions":basis["tax_deductions_json"]}
        if original.input_payload_json["taxMethod"]!="RESIDENT_WAGE":
            raise PolicyPayrollError("PAYROLL_RETRO_TAX_CATEGORY_UNSUPPORTED","奖金等特殊税目更正不可自动套普通工资补差")
        quote=PolicyTaxService(self.tenant,self.actor).quote(tax_input)
        tax=decimal(quote["withholding"]);net=delta-tax
        if net<0:raise PolicyPayrollError("PAYROLL_RETRO_NEGATIVE_NET","补差税额超过本次应发，须专项核对")
        corrected.update({"paymentDate":str(payment_date),"paymentProfileId":str(profile.id),
            "paymentAccountHash":digest({"tenant":self.tenant,"ref":profile.payment_account_ref}),
            "retro":{"sourceResultId":str(source.id),"originalTrialId":str(original.id),"originalHash":original.content_hash,
                "chainHash":chain_hash,"paymentBasisId":basis["id"],"paymentBasisHash":basis["content_hash"],
                "originalGross":str(old_g),"correctedGross":str(gross),"alreadyRecognizedGross":str(prior)},
            "taxDeductions":basis["tax_deductions_json"],"costShares":basis["cost_shares_json"]})
        output={"gross":str(delta),"deduction":str(tax),"net":str(net),"employerCost":"0.00","totalCost":str(delta),
            "costAllocation":allocate_cost(delta,basis["cost_shares_json"]) if basis["cost_shares_json"] else {},
            "taxInput":tax_input,"taxQuote":quote,"historicalRecalculation":lines,
            "lines":[{"itemCode":"RETRO_PAY","name":"历史工资补差","type":"EARNING","amount":str(delta),"ruleId":None},
                     {"itemCode":"IIT","name":"本次补发个人所得税","type":"DEDUCTION","amount":str(tax),"ruleId":None}]}
        return source,corrected,jsonable(output)

    @transaction.atomic
    def trial_retro(self,*,source_result_id,payment_date,payment_profile_id,idempotency_key):
        if not isinstance(idempotency_key,str) or not 1<=len(idempotency_key)<=128:raise PolicyPayrollError("PAYROLL_IDEMPOTENCY_REQUIRED","须提供业务键")
        existing=PayrollTrial.objects.filter(tenant_id=self.tenant,idempotency_key=idempotency_key).first()
        if existing:
            p=existing.input_payload_json
            if existing.purpose!="RETRO" or str(existing.source_result_id)!=str(source_result_id) or p["paymentDate"]!=str(payment_date) or p["paymentProfileId"]!=str(payment_profile_id):
                raise PolicyPayrollError("PAYROLL_RETRO_IDEMPOTENCY_CONFLICT","业务键已对应其他补差")
            return verify_trial(existing)
        source=PayrollResultFact.objects.filter(tenant_id=self.tenant,id=source_result_id).first()
        if not source:raise PolicyPayrollError("PAYROLL_RETRO_SOURCE_NOT_FOUND","原结果不存在")
        self._period(source.payroll_period_id,lock=True)
        source,payload,output=self.build_retro(source_result_id,payment_date,payment_profile_id)
        rev=(PayrollTrial.objects.filter(tenant_id=self.tenant,payroll_period_id=source.payroll_period_id,staff_id=source.staff_id).aggregate(n=Max("revision_no"))["n"] or 0)+1
        trial=PayrollTrial(tenant_id=self.tenant,created_by=self.actor,updated_by=self.actor,payroll_period_id=source.payroll_period_id,
            staff_id=source.staff_id,revision_no=rev,idempotency_key=idempotency_key,purpose="RETRO",source_result_id=source.id,input_payload_json=payload,output_json=output)
        trial.content_hash=trial_digest(trial);trial.save();return trial

    @transaction.atomic
    def approve_retro(self,*,trial_id,expected_hash,decision,note):
        trial=PayrollTrial.objects.filter(tenant_id=self.tenant,id=trial_id,purpose="RETRO").first()
        if not trial:raise PolicyPayrollError("PAYROLL_RETRO_NOT_FOUND","补差试算不存在")
        self._period(trial.payroll_period_id,lock=True);verify_trial(trial)
        if expected_hash!=trial.content_hash:raise PolicyPayrollError("PAYROLL_RETRO_VERSION_CHANGED","复核版本不一致")
        old=PayrollTrialApproval.objects.filter(tenant_id=self.tenant,trial_id=trial.id).first()
        if old:
            if old.decision==decision and old.created_by==self.actor:return old
            raise PolicyPayrollError("PAYROLL_REVIEW_ALREADY_RECORDED","已有复核结论")
        if trial.created_by==self.actor:raise PolicyPayrollError("PAYROLL_SEPARATION_OF_DUTIES","经办与复核不得为同一人")
        if not note or decision not in {"APPROVE","REJECT"}:raise PolicyPayrollError("PAYROLL_REVIEW_NOTE_REQUIRED","须提供结论与说明")
        if decision=="APPROVE":
            p=trial.input_payload_json
            _,payload,output=self.build_retro(trial.source_result_id,p["paymentDate"],p["paymentProfileId"])
            if payload!=p or output!=trial.output_json:raise PolicyPayrollError("PAYROLL_RETRO_STALE","补差依据、历史链或税账已变化，请重新试算")
        return PayrollTrialApproval.objects.create(tenant_id=self.tenant,created_by=self.actor,updated_by=self.actor,
            trial_id=trial.id,trial_hash=expected_hash,decision=decision,note=str(note)[:1000])

    @transaction.atomic
    def apply(self,*,trial_id):
        trial=PayrollTrial.objects.filter(tenant_id=self.tenant,id=trial_id,purpose="RETRO").first()
        if not trial:raise PolicyPayrollError("PAYROLL_RETRO_NOT_FOUND","补差试算不存在")
        self._period(trial.payroll_period_id,lock=True);verify_trial(trial,approved=True)
        old=PayrollRetroApplication.objects.filter(tenant_id=self.tenant,trial_id=trial.id).first()
        if old:return PayrollResultFact.objects.get(tenant_id=self.tenant,id=old.adjustment_result_id)
        p=trial.input_payload_json
        source,payload,out=self.build_retro(trial.source_result_id,p["paymentDate"],p["paymentProfileId"])
        if payload!=p or out!=trial.output_json:raise PolicyPayrollError("PAYROLL_RETRO_STALE","获批补差依据已变化，不沿用旧金额")
        result=PayrollAdjustmentService(self.tenant,self.actor).append_adjustment(source_result_id=source.id,
            adjustment_no="RETRO-"+trial.id.hex,gross_delta=out["gross"],deduction_delta=out["deduction"],net_delta=out["net"],
            reason="APPROVED_POLICY_RECALCULATION",evidence_ref="hr15-trial:"+str(trial.id),_policy_trial_id=trial.id).adjustment
        ref={"trialId":str(trial.id),"trialHash":trial.content_hash};variables={"trialRevision":trial.revision_no}
        snap_payload={"snapshotVersion":SCHEMA,"periodId":str(trial.payroll_period_id),"staffId":str(trial.staff_id),"currencyCode":"CNY","sources":ref,"variables":variables}
        snapshot=PayrollInputSnapshot.objects.create(tenant_id=self.tenant,created_by=self.actor,updated_by=self.actor,payroll_period_id=trial.payroll_period_id,
            staff_id=trial.staff_id,revision_no=trial.revision_no,currency_code="CNY",snapshot_version=SCHEMA,source_versions_json=ref,variables_json=variables,
            content_hash=digest(snap_payload),captured_at=timezone.now())
        batch=PayrollCalculationBatch.objects.create(tenant_id=self.tenant,created_by=self.actor,updated_by=self.actor,payroll_period_id=trial.payroll_period_id,
            batch_no="RETRO-"+trial.id.hex,idempotency_key="retro:"+trial.id.hex,status="COMPLETED",staff_count=1,result_count=1,
            started_at=timezone.now(),completed_at=timezone.now(),rule_set_hash=trial.content_hash,gross_total=out["gross"],deduction_total=out["deduction"],net_total=out["net"])
        for seq,line in enumerate(out["lines"],1):
            PayrollCalculationLine.objects.create(tenant_id=self.tenant,created_by=self.actor,updated_by=self.actor,calculation_batch_id=batch.id,
                payroll_result_id=result.id,staff_id=trial.staff_id,item_code=line["itemCode"],item_name=line["name"],item_type=line["type"],sequence_no=seq,
                amount=line["amount"],currency_code="CNY",rule_version_id=None,explanation_json={"trialId":str(trial.id),"trialHash":trial.content_hash,
                    "inputSnapshotId":str(snapshot.id),"inputContentHash":snapshot.content_hash,"calculation":line,"retroEvidence":payload["retro"]})
        PolicyTaxService(self.tenant,self.actor).reserve(result=result,data=out["taxInput"],approved_quote=out["taxQuote"])
        PayrollRetroApplication.objects.create(tenant_id=self.tenant,created_by=self.actor,updated_by=self.actor,source_result_id=source.id,
            trial_id=trial.id,adjustment_result_id=result.id,prior_chain_hash=payload["retro"]["chainHash"],delta_json={k:out[k] for k in ("gross","deduction","net")})
        from horilla.hr_event_service import emit_registered_event
        emit_registered_event(tenant_id=self.tenant,event_name="hr.payroll.retro.applied",payload={"trialId":str(trial.id),"sourceId":str(source.id),"resultId":str(result.id),"trialHash":trial.content_hash,"actorId":self.actor},correlation_id=self.correlation_id)
        return result
