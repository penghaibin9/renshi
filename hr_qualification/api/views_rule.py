"""HR09 双师规则 API。

Read access may see national/provincial global rule packs plus the selected
school's own packs. School-side writes can only mutate the selected tenant's
SCHOOL/BATCH_OVERRIDE authority and never accept tenant_id from the client.
"""

import uuid

from django.db.models import Q
from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from hr_qualification.api.access import api_guard
from hr_qualification.api.serializers import envelope, error_envelope
from hr_qualification.models import (
    HrDoubleTeacherRule,
    HrDoubleTeacherRulePack,
    HrDoubleTeacherRulePackVersion,
)
from hr_qualification.services.rule_service import RulePackError, RuleService


READ_PERM = "hr.qualification.rule.view"
MANAGE_PERM = "hr.qualification.rule.manage"
PUBLISH_PERM = "hr.qualification.rule.publish"


def _visible_packs(tenant_id):
    return HrDoubleTeacherRulePack.objects.filter(
        Q(tenant_id=tenant_id) | Q(tenant_id__isnull=True)
    )


def _visible_pack_or_none(pack_id, tenant_id):
    return _visible_packs(tenant_id).filter(id=pack_id).first()


def _owned_pack_or_none(pack_id, tenant_id):
    return HrDoubleTeacherRulePack.objects.filter(id=pack_id, tenant_id=tenant_id).first()


def _visible_version_or_none(version_id, tenant_id):
    return (
        HrDoubleTeacherRulePackVersion.objects.select_related("rule_pack_id")
        .filter(id=version_id)
        .filter(Q(rule_pack_id__tenant_id=tenant_id) | Q(rule_pack_id__tenant_id__isnull=True))
        .first()
    )


def _owned_version_or_none(version_id, tenant_id):
    return (
        HrDoubleTeacherRulePackVersion.objects.select_related("rule_pack_id")
        .filter(id=version_id, rule_pack_id__tenant_id=tenant_id)
        .first()
    )


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
        "read_only": pack.tenant_id is None,
    }


@csrf_exempt
@require_http_methods(["GET", "HEAD"])
@api_guard(READ_PERM)
def rule_pack_list(request: HttpRequest) -> JsonResponse:
    tenant_id = request.hr09_tenant_id
    level = request.GET.get("jurisdiction_level")
    qs = _visible_packs(tenant_id)
    if level:
        qs = qs.filter(jurisdiction_level=level)
    packs = list(qs.order_by("jurisdiction_level", "code"))
    return JsonResponse(envelope({"items": [_rule_pack_to_dict(p) for p in packs]}))


@csrf_exempt
@require_http_methods(["POST"])
@api_guard(MANAGE_PERM)
def rule_pack_create(request: HttpRequest) -> JsonResponse:
    try:
        import json

        body = json.loads(request.body)
        tenant_id = request.hr09_tenant_id
        jurisdiction_level = body.get("jurisdiction_level", "SCHOOL")
        if jurisdiction_level not in {"SCHOOL", "BATCH_OVERRIDE"}:
            return JsonResponse(
                error_envelope(
                    "PERMISSION_DENIED",
                    "学校端只能维护本校规则或批次冻结规则，不能创建国家/省级规则。",
                ),
                status=403,
            )
        parent_id = body.get("parent_rule_pack_id")
        if parent_id and _visible_pack_or_none(parent_id, tenant_id) is None:
            return JsonResponse(error_envelope("NOT_FOUND", "Parent Rule Pack not found"), status=404)
        pack = HrDoubleTeacherRulePack.objects.create(
            tenant_id=tenant_id,
            jurisdiction_level=jurisdiction_level,
            jurisdiction_code=body.get("jurisdiction_code", ""),
            code=body["code"],
            name=body["name"],
            parent_rule_pack_id_id=parent_id,
        )
        return JsonResponse(envelope(_rule_pack_to_dict(pack)), status=201)
    except (KeyError, ValueError) as e:
        return JsonResponse(error_envelope("INVALID_REQUEST", str(e)), status=400)
    except Exception as e:
        return JsonResponse(error_envelope("INTERNAL_ERROR", str(e)), status=500)


@csrf_exempt
@require_http_methods(["GET", "HEAD"])
@api_guard(READ_PERM)
def rule_pack_detail(request: HttpRequest, pack_id: str) -> JsonResponse:
    pack = _visible_pack_or_none(pack_id, request.hr09_tenant_id)
    if pack is None:
        return JsonResponse(error_envelope("NOT_FOUND", "Rule Pack not found"), status=404)
    versions = list(
        HrDoubleTeacherRulePackVersion.objects.filter(rule_pack_id=pack).order_by("-version_no")
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


@csrf_exempt
@require_http_methods(["POST"])
@api_guard(MANAGE_PERM)
def rule_version_create(request: HttpRequest, pack_id: str) -> JsonResponse:
    try:
        import json

        pack = _owned_pack_or_none(pack_id, request.hr09_tenant_id)
        if pack is None:
            return JsonResponse(error_envelope("NOT_FOUND", "School Rule Pack not found"), status=404)
        body = json.loads(request.body)
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
    except (KeyError, ValueError) as e:
        return JsonResponse(error_envelope("INVALID_REQUEST", str(e)), status=400)
    except Exception as e:
        return JsonResponse(error_envelope("INTERNAL_ERROR", str(e)), status=500)


@csrf_exempt
@require_http_methods(["GET", "HEAD"])
@api_guard(READ_PERM)
def rule_version_detail(request: HttpRequest, version_id: str) -> JsonResponse:
    version = _visible_version_or_none(version_id, request.hr09_tenant_id)
    if version is None:
        return JsonResponse(error_envelope("NOT_FOUND", "Version not found"), status=404)
    rules = list(HrDoubleTeacherRule.objects.filter(version_id=version).order_by("sequence"))
    return JsonResponse(envelope({
        "id": str(version.id),
        "version_no": version.version_no,
        "effective_from": version.effective_from.isoformat(),
        "status": version.status,
        "checksum": version.checksum,
        "read_only": version.rule_pack_id.tenant_id is None,
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


@csrf_exempt
@require_http_methods(["POST"])
@api_guard(MANAGE_PERM)
def rule_version_validate(request: HttpRequest, version_id: str) -> JsonResponse:
    version = _owned_version_or_none(version_id, request.hr09_tenant_id)
    if version is None:
        return JsonResponse(error_envelope("NOT_FOUND", "School Version not found"), status=404)
    violations = RuleService.validate_inheritance(version)
    return JsonResponse(envelope({"valid": len(violations) == 0, "violations": violations}))


@csrf_exempt
@require_http_methods(["POST"])
@api_guard(PUBLISH_PERM)
def rule_version_publish(request: HttpRequest, version_id: str) -> JsonResponse:
    version = _owned_version_or_none(version_id, request.hr09_tenant_id)
    if version is None:
        return JsonResponse(error_envelope("NOT_FOUND", "School Version not found"), status=404)
    try:
        version = RuleService.publish(version)
        return JsonResponse(envelope({
            "id": str(version.id),
            "status": version.status,
            "checksum": version.checksum,
        }))
    except RulePackError as e:
        return JsonResponse(error_envelope("RULE_WEAKER_THAN_PARENT", str(e)), status=400)


@csrf_exempt
@require_http_methods(["GET", "HEAD"])
@api_guard(READ_PERM)
def rule_version_diff(request: HttpRequest, version_id: str) -> JsonResponse:
    version = _visible_version_or_none(version_id, request.hr09_tenant_id)
    if version is None:
        return JsonResponse(error_envelope("NOT_FOUND", "Version not found"), status=404)
    other_id = request.GET.get("compare_with")
    if not other_id:
        return JsonResponse(error_envelope("MISSING_PARAM", "compare_with is required"), status=400)
    other_version = _visible_version_or_none(other_id, request.hr09_tenant_id)
    if other_version is None:
        return JsonResponse(error_envelope("NOT_FOUND", "Compare Version not found"), status=404)
    diff = RuleService.diff_versions(other_version, version)
    return JsonResponse(envelope(diff))


@csrf_exempt
@require_http_methods(["POST"])
@api_guard(MANAGE_PERM)
def rule_create(request: HttpRequest, version_id: str) -> JsonResponse:
    try:
        import json

        version = _owned_version_or_none(version_id, request.hr09_tenant_id)
        if version is None:
            return JsonResponse(error_envelope("NOT_FOUND", "School Version not found"), status=404)
        body = json.loads(request.body)
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
    except (KeyError, ValueError) as e:
        return JsonResponse(error_envelope("INVALID_REQUEST", str(e)), status=400)
    except Exception as e:
        return JsonResponse(error_envelope("INTERNAL_ERROR", str(e)), status=500)
