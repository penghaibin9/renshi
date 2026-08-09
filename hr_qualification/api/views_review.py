"""
hr_qualification/api/views_review.py —— 评审 + 认定 + 复核 + 风险 API（总册 §110-111）。

端点：
- POST  /api/v1/hr/qualifications/double-teacher/applications/{id}/formal-review
- POST  /api/v1/hr/qualifications/double-teacher/applications/{id}/return
- POST  /api/v1/hr/qualifications/double-teacher/applications/{id}/mark-eligible
- POST  /api/v1/hr/qualifications/double-teacher/score-sheets/{id}/submit
- POST  /api/v1/hr/qualifications/double-teacher/panel-decisions
- POST  /api/v1/hr/qualifications/double-teacher/final-decisions
- GET   /api/v1/hr/qualifications/double-teacher/recognitions
- GET   /api/v1/hr/qualifications/double-teacher/recognitions/{id}
- POST  /api/v1/hr/qualifications/double-teacher/recognitions/{id}/recheck
- POST  /api/v1/hr/qualifications/double-teacher/rechecks/{id}/decide
- GET   /api/v1/hr/qualifications/risks
- POST  /api/v1/hr/qualifications/risks/{id}/acknowledge
- POST  /api/v1/hr/qualifications/risks/{id}/resolve
"""

import uuid

from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt

from hr_qualification.api.serializers import (
    envelope,
    error_envelope,
)
from hr_qualification.constants import ApplicationStatus
from hr_qualification.models import (
    HrDoubleTeacherApplication,
    HrDoubleTeacherFinalDecision,
    HrDoubleTeacherPanelDecision,
    HrDoubleTeacherRecheckCase,
    HrDoubleTeacherRecognition,
    HrDoubleTeacherScoreSheet,
    HrQualificationRiskCase,
)
from hr_qualification.services.recheck_service import RecheckService
from hr_qualification.services.review_service import ReviewError, ReviewService
from hr_qualification.services.risk_service import RiskService


# ---- Formal Review ----

@csrf_exempt
def application_formal_review(request: HttpRequest, app_id: str) -> JsonResponse:
    try:
        import json
        body = json.loads(request.body) if request.body else {}
        app = HrDoubleTeacherApplication.objects.get(id=app_id)
        decision = body.get("decision", "ELIGIBLE")
        app = ReviewService.formal_review(app, decision, body.get("remarks", ""))
        return JsonResponse(envelope({"id": str(app.id), "status": app.status}))
    except ReviewError as e:
        return JsonResponse(error_envelope("REVIEW_ERROR", str(e)), status=400)
    except HrDoubleTeacherApplication.DoesNotExist:
        return JsonResponse(error_envelope("NOT_FOUND", "Application not found"), status=404)


@csrf_exempt
def application_return(request: HttpRequest, app_id: str) -> JsonResponse:
    try:
        app = HrDoubleTeacherApplication.objects.get(id=app_id)
        app = ReviewService.formal_review(app, ApplicationStatus.RETURNED)
        return JsonResponse(envelope({"id": str(app.id), "status": app.status}))
    except ReviewError as e:
        return JsonResponse(error_envelope("REVIEW_ERROR", str(e)), status=400)
    except HrDoubleTeacherApplication.DoesNotExist:
        return JsonResponse(error_envelope("NOT_FOUND", "Application not found"), status=404)


@csrf_exempt
def application_mark_eligible(request: HttpRequest, app_id: str) -> JsonResponse:
    try:
        app = HrDoubleTeacherApplication.objects.get(id=app_id)
        app = ReviewService.formal_review(app, ApplicationStatus.ELIGIBLE)
        return JsonResponse(envelope({"id": str(app.id), "status": app.status}))
    except ReviewError as e:
        return JsonResponse(error_envelope("REVIEW_ERROR", str(e)), status=400)
    except HrDoubleTeacherApplication.DoesNotExist:
        return JsonResponse(error_envelope("NOT_FOUND", "Application not found"), status=404)


# ---- Score Sheets ----

@csrf_exempt
def score_sheet_submit(request: HttpRequest, sheet_id: str) -> JsonResponse:
    try:
        import json
        body = json.loads(request.body) if request.body else {}
        sheet = ReviewService.submit_score(uuid.UUID(sheet_id), body.get("scores_json", {}))
        return JsonResponse(envelope({"id": str(sheet.id), "status": sheet.status}))
    except ReviewError as e:
        return JsonResponse(error_envelope("SCORE_SHEET_ALREADY_LOCKED", str(e)), status=409)
    except HrDoubleTeacherScoreSheet.DoesNotExist:
        return JsonResponse(error_envelope("NOT_FOUND", "Score sheet not found"), status=404)


# ---- Panel Decision ----

@csrf_exempt
def panel_decision_create(request: HttpRequest) -> JsonResponse:
    try:
        import json
        body = json.loads(request.body)
        pd = ReviewService.create_panel_decision(
            application_id=uuid.UUID(body["application_id"]),
            panel_id=uuid.UUID(body["panel_id"]),
            decision=body["decision"],
            recommended_level=body.get("recommended_level", ""),
            reason_summary=body.get("reason_summary", ""),
        )
        return JsonResponse(envelope({"id": str(pd.id), "decision": pd.decision}), status=201)
    except Exception as e:
        return JsonResponse(error_envelope("INTERNAL_ERROR", str(e)), status=500)


# ---- Final Decision ----

@csrf_exempt
def final_decision_create(request: HttpRequest) -> JsonResponse:
    try:
        import json
        body = json.loads(request.body)
        app = HrDoubleTeacherApplication.objects.get(id=body["application_id"])
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
        return JsonResponse(error_envelope("FINAL_DECISION_ALREADY_EXISTS", str(e)), status=409)
    except HrDoubleTeacherApplication.DoesNotExist:
        return JsonResponse(error_envelope("NOT_FOUND", "Application not found"), status=404)
    except Exception as e:
        return JsonResponse(error_envelope("INTERNAL_ERROR", str(e)), status=500)


# ---- Recognition ----

@csrf_exempt
def recognition_list(request: HttpRequest) -> JsonResponse:
    tenant_id = int(request.GET.get("tenant_id", 1))
    status = request.GET.get("status")
    person_id = request.GET.get("person_id")

    qs = HrDoubleTeacherRecognition.objects.filter(tenant_id=tenant_id)
    if status:
        qs = qs.filter(status=status)
    if person_id:
        qs = qs.filter(person_id=person_id)

    qs = qs.order_by("-effective_from")
    items = [{
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
    } for r in qs[:100]]
    return JsonResponse(envelope({"items": items, "total": qs.count()}))


@csrf_exempt
def recognition_detail(request: HttpRequest, recognition_id: str) -> JsonResponse:
    try:
        r = HrDoubleTeacherRecognition.objects.select_related("person_id", "batch_id", "application_id").get(id=recognition_id)
        rechecks = list(
            HrDoubleTeacherRecheckCase.objects
            .filter(recognition_id=r)
            .order_by("-created_at")
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
    except HrDoubleTeacherRecognition.DoesNotExist:
        return JsonResponse(error_envelope("NOT_FOUND", "Recognition not found"), status=404)


# ---- Recheck ----

@csrf_exempt
def recognition_recheck(request: HttpRequest, recognition_id: str) -> JsonResponse:
    try:
        import json
        body = json.loads(request.body) if request.body else {}
        case = RecheckService.open_recheck(
            recognition_id=uuid.UUID(recognition_id),
            trigger=body.get("trigger", "SCHEDULED_REVIEW"),
            due_at=body.get("due_at"),
        )
        return JsonResponse(envelope({
            "id": str(case.id),
            "trigger": case.trigger,
            "status": case.status,
        }), status=201)
    except HrDoubleTeacherRecognition.DoesNotExist:
        return JsonResponse(error_envelope("NOT_FOUND", "Recognition not found"), status=404)


@csrf_exempt
def recheck_decide(request: HttpRequest, recheck_id: str) -> JsonResponse:
    try:
        import json
        body = json.loads(request.body)
        case = RecheckService.decide(
            recheck_id=uuid.UUID(recheck_id),
            decision=body["decision"],
        )
        return JsonResponse(envelope({
            "id": str(case.id),
            "decision": case.decision,
            "status": case.status,
        }))
    except HrDoubleTeacherRecheckCase.DoesNotExist:
        return JsonResponse(error_envelope("NOT_FOUND", "Recheck case not found"), status=404)


# ---- Risk ----

@csrf_exempt
def risk_list(request: HttpRequest) -> JsonResponse:
    tenant_id = int(request.GET.get("tenant_id", 1))
    status = request.GET.get("status")
    severity = request.GET.get("severity")

    qs = HrQualificationRiskCase.objects.filter(tenant_id=tenant_id)
    if status:
        qs = qs.filter(status=status)
    if severity:
        qs = qs.filter(severity=severity)

    qs = qs.order_by("-opened_at")
    items = [{
        "id": str(r.id),
        "person_id": str(r.person_id_id),
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


@csrf_exempt
def risk_acknowledge(request: HttpRequest, risk_id: str) -> JsonResponse:
    try:
        case = RiskService.acknowledge(uuid.UUID(risk_id))
        return JsonResponse(envelope({"id": str(case.id), "status": case.status}))
    except HrQualificationRiskCase.DoesNotExist:
        return JsonResponse(error_envelope("NOT_FOUND", "Risk case not found"), status=404)


@csrf_exempt
def risk_resolve(request: HttpRequest, risk_id: str) -> JsonResponse:
    try:
        import json
        body = json.loads(request.body) if request.body else {}
        case = RiskService.resolve(uuid.UUID(risk_id), body.get("resolution", ""))
        return JsonResponse(envelope({"id": str(case.id), "status": case.status}))
    except HrQualificationRiskCase.DoesNotExist:
        return JsonResponse(error_envelope("NOT_FOUND", "Risk case not found"), status=404)
