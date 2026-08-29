"""HR09 双师评审、认定、复核与风险 API。

Every object is resolved inside the server-selected school before a domain
service is called. State-changing endpoints keep Django CSRF protection.
"""

import uuid

from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_http_methods

from hr_qualification.api.access import api_guard
from hr_qualification.api.serializers import envelope, error_envelope
from hr_qualification.constants import ApplicationStatus
from hr_qualification.models import (
    HrDoubleTeacherApplication,
    HrDoubleTeacherFinalDecision,
    HrDoubleTeacherPanelDecision,
    HrDoubleTeacherRecheckCase,
    HrDoubleTeacherRecognition,
    HrDoubleTeacherReviewPanel,
    HrDoubleTeacherScoreSheet,
    HrQualificationRiskCase,
)
from hr_qualification.services.recheck_service import RecheckService
from hr_qualification.services.review_service import ReviewError, ReviewService
from hr_qualification.services.risk_service import RiskService


FORMAL_REVIEW = "hr.qualification.application.formal_review"
SCORE_REVIEW = "hr.qualification.review.score"
PANEL_MANAGE = "hr.qualification.review.panel_manage"
FINALIZE = "hr.qualification.review.finalize"
RECOGNITION_VIEW = "hr.qualification.recognition.view"
RECOGNITION_RECHECK = "hr.qualification.recognition.recheck"
RISK_VIEW = "hr.qualification.risk.view"
RISK_MANAGE = "hr.qualification.risk.manage"


def _application_or_none(app_id, tenant_id):
    return (
        HrDoubleTeacherApplication.objects.select_related("batch_id")
        .filter(id=app_id, tenant_id=tenant_id, batch_id__tenant_id=tenant_id)
        .first()
    )


def _panel_or_none(panel_id, tenant_id):
    return (
        HrDoubleTeacherReviewPanel.objects.select_related("batch_id")
        .filter(id=panel_id, batch_id__tenant_id=tenant_id)
        .first()
    )


def _recognition_or_none(recognition_id, tenant_id):
    return (
        HrDoubleTeacherRecognition.objects.select_related(
            "person_id", "batch_id", "application_id"
        )
        .filter(id=recognition_id, tenant_id=tenant_id)
        .first()
    )


def _risk_or_none(risk_id, tenant_id):
    return HrQualificationRiskCase.objects.filter(
        id=risk_id, tenant_id=tenant_id
    ).first()


@require_http_methods(["POST"])
@api_guard(FORMAL_REVIEW)
def application_formal_review(request: HttpRequest, app_id: str) -> JsonResponse:
    app = _application_or_none(app_id, request.hr09_tenant_id)
    if app is None:
        return JsonResponse(error_envelope("NOT_FOUND", "Application not found"), status=404)
    try:
        import json

        body = json.loads(request.body) if request.body else {}
        decision = body.get("decision", "ELIGIBLE")
        app = ReviewService.formal_review(app, decision, body.get("remarks", ""))
        return JsonResponse(envelope({"id": str(app.id), "status": app.status}))
    except ReviewError as e:
        return JsonResponse(error_envelope("REVIEW_ERROR", str(e)), status=400)


@require_http_methods(["POST"])
@api_guard(FORMAL_REVIEW)
def application_return(request: HttpRequest, app_id: str) -> JsonResponse:
    app = _application_or_none(app_id, request.hr09_tenant_id)
    if app is None:
        return JsonResponse(error_envelope("NOT_FOUND", "Application not found"), status=404)
    try:
        app = ReviewService.formal_review(app, ApplicationStatus.RETURNED)
        return JsonResponse(envelope({"id": str(app.id), "status": app.status}))
    except ReviewError as e:
        return JsonResponse(error_envelope("REVIEW_ERROR", str(e)), status=400)


@require_http_methods(["POST"])
@api_guard(FORMAL_REVIEW)
def application_mark_eligible(request: HttpRequest, app_id: str) -> JsonResponse:
    app = _application_or_none(app_id, request.hr09_tenant_id)
    if app is None:
        return JsonResponse(error_envelope("NOT_FOUND", "Application not found"), status=404)
    try:
        app = ReviewService.formal_review(app, ApplicationStatus.ELIGIBLE)
        return JsonResponse(envelope({"id": str(app.id), "status": app.status}))
    except ReviewError as e:
        return JsonResponse(error_envelope("REVIEW_ERROR", str(e)), status=400)


@require_http_methods(["POST"])
@api_guard(SCORE_REVIEW)
def score_sheet_submit(request: HttpRequest, sheet_id: str) -> JsonResponse:
    sheet = (
        HrDoubleTeacherScoreSheet.objects.select_related("application_id")
        .filter(
            id=sheet_id,
            application_id__tenant_id=request.hr09_tenant_id,
        )
        .first()
    )
    if sheet is None:
        return JsonResponse(error_envelope("NOT_FOUND", "Score sheet not found"), status=404)
    try:
        import json

        body = json.loads(request.body) if request.body else {}
        sheet = ReviewService.submit_score(sheet.id, body.get("scores_json", {}))
        return JsonResponse(envelope({"id": str(sheet.id), "status": sheet.status}))
    except ReviewError as e:
        return JsonResponse(
            error_envelope("SCORE_SHEET_ALREADY_LOCKED", str(e)), status=409
        )


@require_http_methods(["POST"])
@api_guard(PANEL_MANAGE)
def panel_decision_create(request: HttpRequest) -> JsonResponse:
    try:
        import json

        body = json.loads(request.body)
        application = _application_or_none(
            body["application_id"], request.hr09_tenant_id
        )
        panel = _panel_or_none(body["panel_id"], request.hr09_tenant_id)
        if application is None or panel is None:
            return JsonResponse(
                error_envelope("NOT_FOUND", "Application or panel not found"), status=404
            )
        if str(panel.batch_id_id) != str(application.batch_id_id):
            return JsonResponse(
                error_envelope(
                    "PANEL_SCOPE_MISMATCH",
                    "评审组不属于该申报批次，不能生成评审结论。",
                ),
                status=409,
            )
        pd = ReviewService.create_panel_decision(
            application_id=application.id,
            panel_id=panel.id,
            decision=body["decision"],
            recommended_level=body.get("recommended_level", ""),
            reason_summary=body.get("reason_summary", ""),
        )
        return JsonResponse(
            envelope({"id": str(pd.id), "decision": pd.decision}), status=201
        )
    except (KeyError, ValueError) as e:
        return JsonResponse(error_envelope("INVALID_REQUEST", str(e)), status=400)
    except Exception as e:
        return JsonResponse(error_envelope("INTERNAL_ERROR", str(e)), status=500)


@require_http_methods(["POST"])
@api_guard(FINALIZE)
def final_decision_create(request: HttpRequest) -> JsonResponse:
    try:
        import json

        body = json.loads(request.body)
        app = _application_or_none(body["application_id"], request.hr09_tenant_id)
        if app is None:
            return JsonResponse(error_envelope("NOT_FOUND", "Application not found"), status=404)
        fd, recognition = ReviewService.finalize(
            application=app,
            decision=body["decision"],
            recognized_level=body.get("recognized_level"),
            effective_from=body.get("effective_from"),
            decision_authority=body.get("decision_authority", ""),
            meeting_ref=body.get("meeting_ref", ""),
        )
        result = {
            "final_decision": {"id": str(fd.id), "decision": fd.decision},
        }
        if recognition:
            result["recognition"] = {
                "id": str(recognition.id),
                "recognition_no": recognition.recognition_no,
                "level": recognition.level,
                "status": recognition.status,
            }
        return JsonResponse(envelope(result), status=201)
    except ReviewError as e:
        return JsonResponse(
            error_envelope("FINAL_DECISION_ALREADY_EXISTS", str(e)), status=409
        )
    except (KeyError, ValueError) as e:
        return JsonResponse(error_envelope("INVALID_REQUEST", str(e)), status=400)
    except Exception as e:
        return JsonResponse(error_envelope("INTERNAL_ERROR", str(e)), status=500)


@require_http_methods(["GET", "HEAD"])
@api_guard(RECOGNITION_VIEW)
def recognition_list(request: HttpRequest) -> JsonResponse:
    status = request.GET.get("status")
    person_id = request.GET.get("person_id")
    qs = HrDoubleTeacherRecognition.objects.select_related(
        "person_id", "staff_master_id"
    ).filter(tenant_id=request.hr09_tenant_id)
    if status:
        qs = qs.filter(status=status)
    if person_id:
        qs = qs.filter(person_id=person_id)
    qs = qs.order_by("-effective_from")
    items = [{
        "id": str(r.id),
        "recognition_no": r.recognition_no,
        "person_id": str(r.person_id_id),
        "person": {
            "name": r.person_id.legal_name,
            "staff_no": r.staff_master_id.staff_no if r.staff_master_id_id else "",
        },
        "level": r.level,
        "effective_from": r.effective_from.isoformat(),
        "effective_to": r.effective_to.isoformat() if r.effective_to else None,
        "review_due_at": r.review_due_at.isoformat() if r.review_due_at else None,
        "status": r.status,
        "recognition_authority": r.recognition_authority,
        "version": r.version,
    } for r in qs[:100]]
    return JsonResponse(envelope({"items": items, "total": qs.count()}))


@require_http_methods(["GET", "HEAD"])
@api_guard(RECOGNITION_VIEW)
def recognition_detail(request: HttpRequest, recognition_id: str) -> JsonResponse:
    r = _recognition_or_none(recognition_id, request.hr09_tenant_id)
    if r is None:
        return JsonResponse(error_envelope("NOT_FOUND", "Recognition not found"), status=404)
    rechecks = list(
        HrDoubleTeacherRecheckCase.objects.filter(recognition_id=r).order_by("-created_at")
    )
    return JsonResponse(envelope({
        "id": str(r.id),
        "recognition_no": r.recognition_no,
        "person_id": str(r.person_id_id),
        "level": r.level,
        "effective_from": r.effective_from.isoformat(),
        "effective_to": r.effective_to.isoformat() if r.effective_to else None,
        "review_due_at": r.review_due_at.isoformat() if r.review_due_at else None,
        "status": r.status,
        "recognition_authority": r.recognition_authority,
        "version": r.version,
        "rechecks": [{
            "id": str(rc.id),
            "trigger": rc.trigger,
            "status": rc.status,
            "decision": rc.decision,
            "decided_at": rc.decided_at.isoformat() if rc.decided_at else None,
        } for rc in rechecks],
    }))


@require_http_methods(["POST"])
@api_guard(RECOGNITION_RECHECK)
def recognition_recheck(request: HttpRequest, recognition_id: str) -> JsonResponse:
    recognition = _recognition_or_none(recognition_id, request.hr09_tenant_id)
    if recognition is None:
        return JsonResponse(error_envelope("NOT_FOUND", "Recognition not found"), status=404)
    try:
        import json

        body = json.loads(request.body) if request.body else {}
        case = RecheckService.open_recheck(
            recognition_id=recognition.id,
            trigger=body.get("trigger", "SCHEDULED_REVIEW"),
            due_at=body.get("due_at"),
        )
        return JsonResponse(envelope({
            "id": str(case.id),
            "trigger": case.trigger,
            "status": case.status,
        }), status=201)
    except (ValueError, TypeError) as e:
        return JsonResponse(error_envelope("INVALID_REQUEST", str(e)), status=400)


@require_http_methods(["POST"])
@api_guard(RECOGNITION_RECHECK)
def recheck_decide(request: HttpRequest, recheck_id: str) -> JsonResponse:
    case = (
        HrDoubleTeacherRecheckCase.objects.select_related("recognition_id")
        .filter(
            id=recheck_id,
            recognition_id__tenant_id=request.hr09_tenant_id,
        )
        .first()
    )
    if case is None:
        return JsonResponse(error_envelope("NOT_FOUND", "Recheck case not found"), status=404)
    try:
        import json

        body = json.loads(request.body)
        case = RecheckService.decide(
            recheck_id=case.id,
            decision=body["decision"],
            decided_by=getattr(request.user, "id", None),
        )
        return JsonResponse(envelope({
            "id": str(case.id),
            "decision": case.decision,
            "status": case.status,
        }))
    except (KeyError, ValueError) as e:
        return JsonResponse(error_envelope("INVALID_REQUEST", str(e)), status=400)


@require_http_methods(["GET", "HEAD"])
@api_guard(RISK_VIEW)
def risk_list(request: HttpRequest) -> JsonResponse:
    status = request.GET.get("status")
    severity = request.GET.get("severity")
    qs = HrQualificationRiskCase.objects.select_related("person_id").filter(
        tenant_id=request.hr09_tenant_id
    )
    if status:
        qs = qs.filter(status=status)
    if severity:
        qs = qs.filter(severity=severity)
    qs = qs.order_by("-opened_at")
    items = [{
        "id": str(r.id),
        "person_id": str(r.person_id_id),
        "person": {"name": r.person_id.legal_name},
        "credential_id": str(r.credential_id) if r.credential_id else None,
        "recognition_id": str(r.recognition_id) if r.recognition_id else None,
        "risk_type": r.risk_type,
        "severity": r.severity,
        "opened_at": r.opened_at.isoformat(),
        "owner": r.owner,
        "due_at": r.due_at.isoformat() if r.due_at else None,
        "status": r.status,
        "resolution": r.resolution,
    } for r in qs[:100]]
    return JsonResponse(envelope({"items": items}))


@require_http_methods(["POST"])
@api_guard(RISK_MANAGE)
def risk_acknowledge(request: HttpRequest, risk_id: str) -> JsonResponse:
    risk = _risk_or_none(risk_id, request.hr09_tenant_id)
    if risk is None:
        return JsonResponse(error_envelope("NOT_FOUND", "Risk case not found"), status=404)
    case = RiskService.acknowledge(risk.id)
    return JsonResponse(envelope({"id": str(case.id), "status": case.status}))


@require_http_methods(["POST"])
@api_guard(RISK_MANAGE)
def risk_resolve(request: HttpRequest, risk_id: str) -> JsonResponse:
    risk = _risk_or_none(risk_id, request.hr09_tenant_id)
    if risk is None:
        return JsonResponse(error_envelope("NOT_FOUND", "Risk case not found"), status=404)
    try:
        import json

        body = json.loads(request.body) if request.body else {}
        case = RiskService.resolve(risk.id, body.get("resolution", ""))
        return JsonResponse(envelope({"id": str(case.id), "status": case.status}))
    except ValueError as e:
        return JsonResponse(error_envelope("INVALID_REQUEST", str(e)), status=400)
