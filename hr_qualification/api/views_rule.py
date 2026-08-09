"""
hr_qualification/api/views_rule.py —— 双师规则 API（总册 §108）。

端点：
- GET/POST  /api/v1/hr/qualifications/double-teacher/rule-packs
- POST      /api/v1/hr/qualifications/double-teacher/rule-packs/{id}/versions
- GET       /api/v1/hr/qualifications/double-teacher/rule-versions/{id}
- POST      /api/v1/hr/qualifications/double-teacher/rule-versions/{id}/validate
- POST      /api/v1/hr/qualifications/double-teacher/rule-versions/{id}/publish
- GET       /api/v1/hr/qualifications/double-teacher/rule-versions/{id}/diff
"""

import uuid

from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from hr_qualification.api.serializers import (
    HrRulePackSerializer,
    HrRulePackVersionSerializer,
    HrDoubleTeacherRuleSerializer,
    envelope,
    error_envelope,
)
from hr_qualification.models import (
    HrDoubleTeacherRule,
    HrDoubleTeacherRulePack,
    HrDoubleTeacherRulePackVersion,
)
from hr_qualification.services.rule_service import RulePackError, RuleService


def _rule_pack_to_dict(pack: HrDoubleTeacherRulePack) -> dict:
    return {
        "id": str(pack.id),
        "tenant_id": pack.tenant_id,
        "jurisdiction_level": pack.jurisdiction_level,
        "jurisdiction_code": pack.jurisdiction_code,
        "code": pack.code,
        "name": pack.name,
        "parent_rule_pack_id": str(pack.parent_rule_pack_id_id) if pack.parent_rule_pack_id_id else None,
        "status": pack.status,
        "version": pack.version,
    }


# ---- Rule Packs ----

@csrf_exempt
@require_http_methods(["GET", "HEAD"])
def rule_pack_list(request: HttpRequest) -> JsonResponse:
    tenant_id = request.GET.get("tenant_id")
    filters = {}
    if tenant_id is not None:
        filters["tenant_id"] = int(tenant_id)
    else:
        filters["tenant_id__isnull"] = True

    level = request.GET.get("jurisdiction_level")
    if level:
        filters["jurisdiction_level"] = level

    packs = list(HrDoubleTeacherRulePack.objects.filter(**filters).order_by("jurisdiction_level", "code"))
    return JsonResponse(envelope({"items": [_rule_pack_to_dict(p) for p in packs]}))


@csrf_exempt
@require_http_methods(["POST"])
def rule_pack_create(request: HttpRequest) -> JsonResponse:
    try:
        import json
        body = json.loads(request.body)
        pack = HrDoubleTeacherRulePack.objects.create(
            tenant_id=body.get("tenant_id"),
            jurisdiction_level=body["jurisdiction_level"],
            jurisdiction_code=body.get("jurisdiction_code", ""),
            code=body["code"],
            name=body["name"],
            parent_rule_pack_id_id=body.get("parent_rule_pack_id"),
        )
        return JsonResponse(envelope(_rule_pack_to_dict(pack)), status=201)
    except Exception as e:
        return JsonResponse(error_envelope("INTERNAL_ERROR", str(e)), status=500)


@csrf_exempt
def rule_pack_detail(request: HttpRequest, pack_id: str) -> JsonResponse:
    try:
        pack = HrDoubleTeacherRulePack.objects.get(id=pack_id)
        versions = list(
            HrDoubleTeacherRulePackVersion.objects
            .filter(rule_pack_id=pack)
            .order_by("-version_no")
        )
        return JsonResponse(envelope({
            "pack": _rule_pack_to_dict(pack),
            "versions": [{
                "id": str(v.id),
                "version_no": v.version_no,
                "effective_from": v.effective_from.isoformat(),
                "effective_to": v.effective_to.isoformat() if v.effective_to else None,
                "status": v.status,
                "checksum": v.checksum,
            } for v in versions],
        }))
    except HrDoubleTeacherRulePack.DoesNotExist:
        return JsonResponse(error_envelope("NOT_FOUND", "Rule Pack not found"), status=404)


# ---- Rule Pack Versions ----

@csrf_exempt
@require_http_methods(["POST"])
def rule_version_create(request: HttpRequest, pack_id: str) -> JsonResponse:
    try:
        import json
        body = json.loads(request.body)
        pack = HrDoubleTeacherRulePack.objects.get(id=pack_id)
        version = HrDoubleTeacherRulePackVersion.objects.create(
            rule_pack_id=pack,
            version_no=body["version_no"],
            effective_from=body["effective_from"],
            effective_to=body.get("effective_to"),
            policy_document_ids=body.get("policy_document_ids"),
        )
        return JsonResponse(envelope({
            "id": str(version.id),
            "version_no": version.version_no,
            "status": version.status,
        }), status=201)
    except Exception as e:
        return JsonResponse(error_envelope("INTERNAL_ERROR", str(e)), status=500)


@csrf_exempt
def rule_version_detail(request: HttpRequest, version_id: str) -> JsonResponse:
    try:
        version = HrDoubleTeacherRulePackVersion.objects.get(id=version_id)
        rules = list(
            HrDoubleTeacherRule.objects
            .filter(version_id=version)
            .order_by("sequence")
        )
        return JsonResponse(envelope({
            "id": str(version.id),
            "version_no": version.version_no,
            "effective_from": version.effective_from.isoformat(),
            "status": version.status,
            "checksum": version.checksum,
            "rules": [{
                "id": str(r.id),
                "level": r.level,
                "dimension_code": r.dimension_code,
                "rule_code": r.rule_code,
                "rule_type": r.rule_type,
                "operator": r.operator,
                "expected_value_json": r.expected_value_json,
                "hard_or_soft": r.hard_or_soft,
                "source_provider": r.source_provider,
                "manual_review_required": r.manual_review_required,
                "sequence": r.sequence,
            } for r in rules],
        }))
    except HrDoubleTeacherRulePackVersion.DoesNotExist:
        return JsonResponse(error_envelope("NOT_FOUND", "Version not found"), status=404)


@csrf_exempt
@require_http_methods(["POST"])
def rule_version_validate(request: HttpRequest, version_id: str) -> JsonResponse:
    try:
        version = HrDoubleTeacherRulePackVersion.objects.get(id=version_id)
        violations = RuleService.validate_inheritance(version)
        return JsonResponse(envelope({
            "valid": len(violations) == 0,
            "violations": violations,
        }))
    except HrDoubleTeacherRulePackVersion.DoesNotExist:
        return JsonResponse(error_envelope("NOT_FOUND", "Version not found"), status=404)


@csrf_exempt
@require_http_methods(["POST"])
def rule_version_publish(request: HttpRequest, version_id: str) -> JsonResponse:
    try:
        version = HrDoubleTeacherRulePackVersion.objects.get(id=version_id)
        version = RuleService.publish(version)
        return JsonResponse(envelope({
            "id": str(version.id),
            "status": version.status,
            "checksum": version.checksum,
        }))
    except RulePackError as e:
        return JsonResponse(error_envelope("RULE_WEAKER_THAN_PARENT", str(e)), status=400)
    except HrDoubleTeacherRulePackVersion.DoesNotExist:
        return JsonResponse(error_envelope("NOT_FOUND", "Version not found"), status=404)


@csrf_exempt
def rule_version_diff(request: HttpRequest, version_id: str) -> JsonResponse:
    try:
        version = HrDoubleTeacherRulePackVersion.objects.get(id=version_id)
        other_id = request.GET.get("compare_with")
        if not other_id:
            return JsonResponse(error_envelope("MISSING_PARAM", "compare_with is required"), status=400)

        other_version = HrDoubleTeacherRulePackVersion.objects.get(id=other_id)
        diff = RuleService.diff_versions(other_version, version)
        return JsonResponse(envelope(diff))
    except HrDoubleTeacherRulePackVersion.DoesNotExist:
        return JsonResponse(error_envelope("NOT_FOUND", "Version not found"), status=404)


# ---- Rule CRUD within a version ----

@csrf_exempt
@require_http_methods(["POST"])
def rule_create(request: HttpRequest, version_id: str) -> JsonResponse:
    try:
        import json
        body = json.loads(request.body)
        version = HrDoubleTeacherRulePackVersion.objects.get(id=version_id)
        rule = HrDoubleTeacherRule.objects.create(
            version_id=version,
            level=body["level"],
            dimension_code=body["dimension_code"],
            rule_code=body["rule_code"],
            rule_type=body["rule_type"],
            operator=body.get("operator", ">="),
            expected_value_json=body.get("expected_value_json"),
            hard_or_soft=body.get("hard_or_soft", "HARD"),
            source_provider=body.get("source_provider", ""),
            manual_review_required=body.get("manual_review_required", False),
            sequence=body.get("sequence", 0),
        )
        return JsonResponse(envelope({"id": str(rule.id), "rule_code": rule.rule_code}), status=201)
    except Exception as e:
        return JsonResponse(error_envelope("INTERNAL_ERROR", str(e)), status=500)
