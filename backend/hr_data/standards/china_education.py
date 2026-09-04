"""Chinese higher-education exchange metadata and validation.

Internal HR domain codes remain stable.  This module owns the external
standard profile applied to frozen exchange datasets so upgrades append a new
profile/version instead of leaking standards-specific codes into core models.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date

from django.utils import timezone


PROFILE_CODE = "CHINA_HIGHER_EDUCATION_HR"
SEMANTIC_STANDARDS = (
    {"code": "GB/T 29808-2013", "name": "信息技术 学习、教育和培训 高等学校管理信息"},
    {"code": "JY/T 0637-2022", "name": "教育系统人员基础数据"},
)
CLASSIFICATION_STANDARD = {
    "code": "JY/T 0661-2025",
    "name": "教育数据分类分级指南",
}

STAFF_CATEGORIES = {
    "教职工数据": ("教职工基础数据", "教职工管理数据"),
}
SECURITY_LEVELS = {
    "L1": "一般数据（一级）",
    "L2": "一般数据（二级）",
    "L3": "一般数据（三级）",
    "L4": "重要数据",
    "L5": "核心数据",
}
SCOPES = {
    "WHOLE_UNIVERSITY": "全校范围",
    "ORGANIZATION_UNIT": "校内单位范围",
    "INDIVIDUAL_CASE": "单项业务范围",
}


class ChinaEducationStandardError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def standard_catalog() -> dict:
    """Return safe metadata for Chinese labels and client-side form choices."""

    return {
        "profileCode": PROFILE_CODE,
        "profileName": "中国高校人事数据交换",
        "semanticStandards": [dict(item) for item in SEMANTIC_STANDARDS],
        "classificationStandard": dict(CLASSIFICATION_STANDARD),
        "categories": [
            {"primary": primary, "secondary": list(secondaries)}
            for primary, secondaries in STAFF_CATEGORIES.items()
        ],
        "securityLevels": [
            {"code": code, "name": name} for code, name in SECURITY_LEVELS.items()
        ],
        "scopes": [{"code": code, "name": name} for code, name in SCOPES.items()],
        "wholeUniversityStaffMinimumLevel": "L3",
    }


def normalize_exchange_schema(schema: dict, *, record_count: int) -> dict:
    """Validate and canonicalize a Chinese higher-education standard profile.

    Datasets without ``standardProfile`` remain valid for non-education or
    legacy integrations.  Once the profile is selected, classification
    evidence is mandatory and the canonical standard identifiers are written
    by the server rather than trusted from the request.
    """

    normalized = deepcopy(schema)
    profile = normalized.get("standardProfile")
    if profile is None:
        return normalized
    if not isinstance(profile, dict):
        raise ChinaEducationStandardError(
            "EXCHANGE_STANDARD_PROFILE_INVALID", "standardProfile 必须是 JSON 对象"
        )
    if str(profile.get("profileCode") or "").strip().upper() != PROFILE_CODE:
        raise ChinaEducationStandardError(
            "EXCHANGE_STANDARD_PROFILE_UNSUPPORTED", "不支持的数据交换标准配置"
        )

    classification = profile.get("classification")
    if not isinstance(classification, dict):
        raise ChinaEducationStandardError(
            "EXCHANGE_CLASSIFICATION_REQUIRED", "使用中国高校标准时必须完成数据分类分级"
        )
    primary = str(classification.get("primaryCategory") or "").strip()
    secondary = str(classification.get("secondaryCategory") or "").strip()
    if secondary not in STAFF_CATEGORIES.get(primary, ()):
        raise ChinaEducationStandardError(
            "EXCHANGE_CLASSIFICATION_CATEGORY_INVALID", "教职工数据分类不符合 JY/T 0661-2025"
        )
    level = str(classification.get("securityLevel") or "").strip().upper()
    if level not in SECURITY_LEVELS:
        raise ChinaEducationStandardError(
            "EXCHANGE_CLASSIFICATION_LEVEL_INVALID", "数据级别必须是 L1 至 L5"
        )
    scope = str(classification.get("scope") or "").strip().upper()
    if scope not in SCOPES:
        raise ChinaEducationStandardError(
            "EXCHANGE_CLASSIFICATION_SCOPE_INVALID", "必须明确数据覆盖范围"
        )
    sensitive = classification.get("containsSensitivePersonalInformation")
    if not isinstance(sensitive, bool):
        raise ChinaEducationStandardError(
            "EXCHANGE_SENSITIVE_FLAG_REQUIRED", "必须明确是否包含敏感个人信息"
        )
    basis = str(classification.get("classificationBasis") or "").strip()
    if not 10 <= len(basis) <= 500:
        raise ChinaEducationStandardError(
            "EXCHANGE_CLASSIFICATION_BASIS_INVALID", "定级依据应填写 10 至 500 个字符"
        )
    classified_at_raw = str(classification.get("classifiedAt") or "").strip()
    try:
        classified_at = date.fromisoformat(classified_at_raw)
    except ValueError as exc:
        raise ChinaEducationStandardError(
            "EXCHANGE_CLASSIFIED_AT_INVALID", "定级日期必须是有效日期"
        ) from exc
    if classified_at > timezone.localdate():
        raise ChinaEducationStandardError(
            "EXCHANGE_CLASSIFIED_AT_INVALID", "定级日期不能晚于当前日期"
        )

    if scope == "WHOLE_UNIVERSITY" and int(level[1:]) < 3:
        raise ChinaEducationStandardError(
            "EXCHANGE_CLASSIFICATION_LEVEL_TOO_LOW",
            "高校全校范围的教职工数据不得低于 L3",
        )
    approval_reference = str(classification.get("approvalReference") or "").strip()
    if level in {"L4", "L5"} and not approval_reference:
        raise ChinaEducationStandardError(
            "EXCHANGE_CLASSIFICATION_APPROVAL_REQUIRED",
            "L4/L5 数据必须填写主管部门报批审定依据",
        )
    if len(approval_reference) > 200:
        raise ChinaEducationStandardError(
            "EXCHANGE_CLASSIFICATION_APPROVAL_INVALID", "报批审定依据不能超过 200 个字符"
        )

    normalized["standardProfile"] = {
        "profileCode": PROFILE_CODE,
        "profileName": "中国高校人事数据交换",
        "semanticStandards": [dict(item) for item in SEMANTIC_STANDARDS],
        "classificationStandard": dict(CLASSIFICATION_STANDARD),
        "classification": {
            "primaryCategory": primary,
            "secondaryCategory": secondary,
            "securityLevel": level,
            "securityLevelName": SECURITY_LEVELS[level],
            "scope": scope,
            "scopeName": SCOPES[scope],
            "containsSensitivePersonalInformation": sensitive,
            "classificationBasis": basis,
            "classifiedAt": classified_at.isoformat(),
            "approvalReference": approval_reference,
            "recordCountAtFreeze": record_count,
        },
    }
    return normalized


def classification_summary(schema: dict) -> dict | None:
    profile = schema.get("standardProfile") if isinstance(schema, dict) else None
    classification = profile.get("classification") if isinstance(profile, dict) else None
    if not isinstance(classification, dict):
        return None
    return {
        "profileCode": profile.get("profileCode"),
        "primaryCategory": classification.get("primaryCategory"),
        "secondaryCategory": classification.get("secondaryCategory"),
        "securityLevel": classification.get("securityLevel"),
        "scope": classification.get("scope"),
        "containsSensitivePersonalInformation": classification.get(
            "containsSensitivePersonalInformation"
        ),
        "classifiedAt": classification.get("classifiedAt"),
    }
