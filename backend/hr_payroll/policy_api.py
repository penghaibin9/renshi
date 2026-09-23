"""Policy depth endpoints on the existing tenant/permission/CSRF boundary."""
from functools import wraps
import json
from uuid import UUID
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.http import JsonResponse
from hr_payroll.api import (HrPayrollAccessError, READ_PERMISSION, _error, _json_body, resolve_request_tenant)
from hr_payroll.authority_registry import (PERM_RULE_MANAGE, PERM_INPUT_MANAGE, PERM_REVIEW,
                                          PERM_CALCULATE, PERM_RECONCILE, PERM_PAYSLIP_SENSITIVE)
from hr_payroll.models import PayrollPeriod, PayrollProfile
from hr_payroll.policy_models import PayrollTrial, PayrollTrialApproval, PayrollTaxAccount, PayrollTaxReservation
from hr_payroll.services.calculation_service import PayrollCalculationError
from hr_payroll.services.policy_configuration_service import MODELS, PolicyConfigurationService, record
from hr_payroll.services.policy_payroll_service import PolicyPayrollService, verify_trial
from hr_payroll.services.policy_math import PolicyPayrollError


def permitted(request, permissions):
    tenant = resolve_request_tenant(request, required_permission=READ_PERMISSION)
    user = request.user
    if not (user.is_superuser or any(user.has_perm(p) for p in permissions)):
        raise HrPayrollAccessError("PERMISSION_DENIED", "当前账号无此薪酬业务权限")
    return tenant


def guarded(methods, permissions):
    def decorator(fn):
        @wraps(fn)
        def wrapper(request, *args, **kwargs):
            if request.method not in methods:
                return _error("METHOD_NOT_ALLOWED", status=405)
            try:
                tenant=permitted(request, permissions)
                if request.content_type == "application/json" and len(request.body) > 1024*1024:
                    return _error("PAYROLL_REQUEST_TOO_LARGE", "配置请求超过1 MiB", status=413)
                result=fn(request,tenant,*args,**kwargs)
                result["Cache-Control"]="no-store"
                result["X-Content-Type-Options"]="nosniff"
                return result
            except HrPayrollAccessError as exc:
                return _error(exc.code, str(exc), status=403)
            except (PolicyPayrollError,PayrollCalculationError) as exc:
                status=404 if "NOT_FOUND" in exc.code else 409 if any(x in exc.code for x in ("CONFLICT","STALE","CHANGED","LOCKED","OVERLAP","PENDING")) else 400
                return _error(exc.code,str(exc),status=status)
            except (ValidationError,ValueError,TypeError,KeyError) as exc:
                # No raw ORM exception or financial payload in user responses/logs.
                return _error("PAYROLL_INPUT_INVALID", "字段类型、日期、编号或金额无效，请核对表单", status=400)
            except IntegrityError:
                return _error("PAYROLL_CONCURRENT_CONFLICT", "编号或并发版本已存在，请读取原记录，不重复提交", status=409)
        return wrapper
    return decorator


def _page(request, queryset):
    page=max(1,int(request.GET.get("page",1)));size=min(100,max(1,int(request.GET.get("pageSize",30))))
    total=queryset.count();rows=list(queryset[(page-1)*size:page*size])
    return rows,{"page":page,"pageSize":size,"total":total,"hasNext":page*size<total}


@guarded({"GET"},[PERM_RULE_MANAGE,PERM_INPUT_MANAGE,PERM_REVIEW,PERM_CALCULATE])
def options(request,tenant):
    from hr_staff.models import HrEmploymentRelationship,HrStaffAssignment,HrStaffMaster
    q=str(request.GET.get("q","")).strip()[:100]
    staff=HrStaffMaster.objects.filter(tenant_id=tenant,person_id__tenant_id=tenant).select_related("person_id")
    if q:
        from django.db.models import Q
        staff=staff.filter(Q(staff_no__icontains=q)|Q(person_id__legal_name__icontains=q))
    staff,meta=_page(request,staff.order_by("staff_no","id"))
    ids=[s.id for s in staff]
    return JsonResponse({"data":{
        "staff":[{"id":str(s.id),"label":s.person_id.legal_name+" · "+s.staff_no} for s in staff],"staffPage":meta,
        "profiles":[{"id":str(p.id),"staffId":str(p.staff_id),"payGroupCode":p.pay_group_code,"identityNo":p.payroll_identity_no} for p in PayrollProfile.objects.filter(tenant_id=tenant,staff_id__in=ids).order_by("payroll_identity_no")],
        "relationships":[{"id":str(x.id),"staffId":str(x.staff_id_id),"type":x.relationship_type,"from":str(x.effective_from),"to":str(x.effective_to or ""),"status":x.status} for x in HrEmploymentRelationship.objects.filter(tenant_id=tenant,staff_id__in=ids).order_by("effective_from")],
        "periods":[{"id":str(p.id),"code":p.period_code,"status":p.status,"engine":p.engine_version,"purpose":p.payroll_purpose,"paymentDate":str(p.payment_date or "")} for p in PayrollPeriod.objects.filter(tenant_id=tenant).order_by("-start_date","period_code")[:120]],
    }})


@guarded({"GET","POST"},[PERM_RULE_MANAGE,PERM_INPUT_MANAGE,PERM_REVIEW,PERM_CALCULATE])
def configurations(request,tenant,kind):
    kind=kind.upper();model=MODELS.get(kind)
    if model is None:raise PolicyPayrollError("PAYROLL_CONFIGURATION_KIND_INVALID","未知配置类型")
    required=PERM_RULE_MANAGE if kind in {"POLICY","STANDARD","RULE"} else PERM_INPUT_MANAGE
    if request.method=="POST":
        permitted(request,[required])
        obj=PolicyConfigurationService(tenant,request.user.id).create(kind,_json_body(request))
        return JsonResponse({"data":record(obj)},status=201)
    if kind in {"BASIS","WORKLOAD"}:
        permitted(request,[PERM_INPUT_MANAGE,PERM_REVIEW,PERM_CALCULATE,PERM_PAYSLIP_SENSITIVE])
    qs=model.objects.filter(tenant_id=tenant).order_by("-created_at","id")
    group=request.GET.get("payGroupCode")
    if group and kind in {"POLICY","STANDARD","RULE"}:qs=qs.filter(pay_group_code=group)
    if kind=="RULE":qs=qs.exclude(pay_group_code="")
    if request.GET.get("status"):qs=qs.filter(status=request.GET["status"])
    if kind in {"BASIS","WORKLOAD"} and request.GET.get("staffId"):qs=qs.filter(staff_id=UUID(request.GET["staffId"]))
    rows,meta=_page(request,qs)
    return JsonResponse({"data":[record(x) for x in rows],**meta})


@guarded({"POST"},[PERM_REVIEW])
def publish_configuration(request,tenant,kind,object_id):
    # Review privilege is distinct from draft creation; service enforces two actual people.
    obj=PolicyConfigurationService(tenant,request.user.id).publish(kind,object_id)
    return JsonResponse({"data":record(obj)})


@guarded({"GET","POST"},[PERM_CALCULATE,PERM_REVIEW,PERM_INPUT_MANAGE])
def trials(request,tenant):
    if request.method=="POST":
        permitted(request,[PERM_CALCULATE]);body=_json_body(request)
        if set(body)-{"periodId","staffId","idempotencyKey"}:
            raise PolicyPayrollError("PAYROLL_TRIAL_INPUT_FORBIDDEN","试算只接受人员、期间和业务键，不接受前端金额或公式")
        trial=PolicyPayrollService(tenant,request.user.id).trial(period_id=body["periodId"],staff_id=body["staffId"],idempotency_key=body["idempotencyKey"])
        return JsonResponse({"data":trial_summary(trial)},status=201)
    qs=PayrollTrial.objects.filter(tenant_id=tenant).order_by("-created_at","id")
    if request.GET.get("periodId"):qs=qs.filter(payroll_period_id=UUID(request.GET["periodId"]))
    if request.GET.get("staffId"):qs=qs.filter(staff_id=UUID(request.GET["staffId"]))
    rows,meta=_page(request,qs)
    approvals={str(x.trial_id):x.decision for x in PayrollTrialApproval.objects.filter(tenant_id=tenant,trial_id__in=[x.id for x in rows])}
    return JsonResponse({"data":[{**trial_summary(x),"review":approvals.get(str(x.id),"PENDING")} for x in rows],**meta})


def trial_summary(trial):
    out=trial.output_json
    return {"id":str(trial.id),"periodId":str(trial.payroll_period_id),"staffId":str(trial.staff_id),"revision":trial.revision_no,
            "purpose":trial.purpose,"hash":trial.content_hash,"gross":out.get("gross"),"deduction":out.get("deduction"),
            "net":out.get("net"),"totalCost":out.get("totalCost"),"createdBy":trial.created_by,"createdAt":str(trial.created_at)}


@guarded({"GET"},[PERM_CALCULATE,PERM_REVIEW,PERM_INPUT_MANAGE,PERM_PAYSLIP_SENSITIVE])
def trial_detail(request,tenant,trial_id):
    trial=PayrollTrial.objects.filter(tenant_id=tenant,id=trial_id).first()
    if not trial:raise PolicyPayrollError("PAYROLL_TRIAL_NOT_FOUND","本校试算不存在")
    verify_trial(trial)
    return JsonResponse({"data":{**trial_summary(trial),"input":trial.input_payload_json,"calculation":trial.output_json}})


@guarded({"POST"},[PERM_REVIEW])
def review_trial(request,tenant,trial_id):
    body=_json_body(request)
    if set(body)-{"expectedHash","decision","note"}:raise PolicyPayrollError("PAYROLL_REVIEW_INPUT_INVALID","复核字段不合法")
    found=PayrollTrial.objects.filter(tenant_id=tenant,id=trial_id).first()
    from .services.policy_retro_service import PolicyRetroService
    service=PolicyRetroService(tenant,request.user.id).approve_retro if found and found.purpose=="RETRO" else PolicyPayrollService(tenant,request.user.id).approve
    obj=service(trial_id=trial_id,expected_hash=body.get("expectedHash"),
                 decision=body.get("decision","APPROVE"),note=body.get("note",""))
    return JsonResponse({"data":record(obj)})


@guarded({"GET"},[PERM_RECONCILE,PERM_PAYSLIP_SENSITIVE])
def tax_accounts(request,tenant):
    qs=PayrollTaxAccount.objects.filter(tenant_id=tenant).order_by("-tax_year","withholding_agent_code","person_id")
    if request.GET.get("year"):qs=qs.filter(tax_year=int(request.GET["year"]))
    rows,meta=_page(request,qs)
    return JsonResponse({"data":[record(x) for x in rows],**meta})


@guarded({"GET"},[PERM_RECONCILE,PERM_PAYSLIP_SENSITIVE])
def settlement_status(request,tenant):
    qs=PayrollTaxReservation.objects.filter(tenant_id=tenant).order_by("-created_at","id")
    if request.GET.get("status"):qs=qs.filter(status=request.GET["status"])
    rows,meta=_page(request,qs)
    return JsonResponse({"data":[{"id":str(x.id),"resultId":str(x.payroll_result_id),"staffId":str(x.staff_id),
               "status":x.status,"receiptRef":x.receipt_ref,"paymentDate":x.input_json["paymentDate"],"tax":x.quote_json["withholding"]} for x in rows],**meta})


def _import_permission(request, kind):
    return permitted(request,[PERM_RULE_MANAGE if kind.upper()=="STANDARD" else PERM_INPUT_MANAGE])


@guarded({"GET"},[PERM_RULE_MANAGE,PERM_INPUT_MANAGE])
def import_template(request,tenant,kind):
    from django.http import HttpResponse
    from .services.policy_import_service import HEADERS,workbook_bytes
    kind=kind.upper();_import_permission(request,kind)
    if kind not in HEADERS:raise PolicyPayrollError("PAYROLL_IMPORT_KIND_INVALID","不支持此导入类型")
    response=HttpResponse(workbook_bytes(kind),content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"]=f'attachment; filename="payroll-{kind.lower()}-template.xlsx"'
    return response


@guarded({"POST"},[PERM_RULE_MANAGE,PERM_INPUT_MANAGE])
def import_preview(request,tenant,kind):
    from .services.policy_import_service import PayrollPolicyImportService
    _import_permission(request,kind)
    upload=request.FILES.get("file")
    if not upload:raise PolicyPayrollError("PAYROLL_IMPORT_FILE_REQUIRED","请选择xlsx文件")
    if upload.size>8*1024*1024:raise PolicyPayrollError("PAYROLL_IMPORT_SIZE_LIMIT","文件超过8 MiB")
    stage=PayrollPolicyImportService(tenant,request.user.id).preview(kind,upload.read())
    return JsonResponse({"data":{"id":str(stage.id),"hash":stage.stage_hash,"rows":stage.rows_json,"errors":stage.errors_json,"status":stage.status}},status=201)


@guarded({"POST"},[PERM_RULE_MANAGE,PERM_INPUT_MANAGE])
def import_confirm(request,tenant,stage_id):
    from .policy_models import PayrollImportStage
    from .services.policy_import_service import PayrollPolicyImportService
    stage=PayrollImportStage.objects.filter(tenant_id=tenant,id=stage_id,created_by=request.user.id).first()
    if not stage:raise PolicyPayrollError("PAYROLL_IMPORT_NOT_FOUND","本人的预览不存在")
    _import_permission(request,stage.kind)
    stage=PayrollPolicyImportService(tenant,request.user.id).confirm(stage.id,_json_body(request).get("expectedHash"))
    return JsonResponse({"data":{"id":str(stage.id),"status":stage.status,"draftIds":stage.applied_ids_json}})


@guarded({"GET"},[PERM_RULE_MANAGE,PERM_INPUT_MANAGE])
def import_errors(request,tenant,stage_id):
    from .policy_models import PayrollImportStage
    from .services.policy_import_service import workbook_bytes
    from django.http import HttpResponse
    stage=PayrollImportStage.objects.filter(tenant_id=tenant,id=stage_id,created_by=request.user.id).first()
    if not stage:raise PolicyPayrollError("PAYROLL_IMPORT_NOT_FOUND","本人的预览不存在")
    _import_permission(request,stage.kind)
    response=HttpResponse(workbook_bytes(stage.kind,[x["data"] for x in stage.rows_json],stage.errors_json),content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"]='attachment; filename="payroll-import-errors.xlsx"'
    return response


@guarded({"POST"},[PERM_CALCULATE])
def retro_trial(request,tenant):
    from .services.policy_retro_service import PolicyRetroService
    body=_json_body(request)
    if set(body)-{"sourceResultId","paymentDate","paymentProfileId","idempotencyKey"}:
        raise PolicyPayrollError("PAYROLL_RETRO_INPUT_FORBIDDEN","补差不接受前端计算的差额")
    trial=PolicyRetroService(tenant,request.user.id).trial_retro(source_result_id=body["sourceResultId"],payment_date=body["paymentDate"],payment_profile_id=body["paymentProfileId"],idempotency_key=body["idempotencyKey"])
    return JsonResponse({"data":trial_summary(trial)},status=201)


@guarded({"POST"},[PERM_CALCULATE])
def retro_apply(request,tenant,trial_id):
    from .services.policy_retro_service import PolicyRetroService
    if _json_body(request):raise PolicyPayrollError("PAYROLL_RETRO_INPUT_FORBIDDEN","应用补差只引用已批准试算，不接受额外金额")
    result=PolicyRetroService(tenant,request.user.id).apply(trial_id=trial_id)
    return JsonResponse({"data":{"id":str(result.id),"number":result.result_no,"status":result.status,"gross":str(result.gross_amount),"deduction":str(result.deduction_amount),"net":str(result.net_amount)}})

@guarded({"GET"},[PERM_CALCULATE,PERM_REVIEW,PERM_PAYSLIP_SENSITIVE])
def export_trial(request,tenant,trial_id):
    from django.http import HttpResponse
    from horilla.hr_event_service import emit_registered_event
    from .services.policy_export_service import trial_workbook
    trial=PayrollTrial.objects.filter(tenant_id=tenant,id=trial_id).first()
    if not trial:raise PolicyPayrollError("PAYROLL_TRIAL_NOT_FOUND","本校试算不存在")
    blob=trial_workbook(trial)
    emit_registered_event(tenant_id=tenant,event_name="hr.payroll.trial.exported",payload={"trialId":str(trial.id),"hash":trial.content_hash,"actorId":request.user.id},correlation_id="")
    response=HttpResponse(blob,content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"]=f'attachment; filename="payroll-trial-{trial.id}.xlsx"'
    return response
