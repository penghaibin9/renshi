"""
hr_recruitment/policies/privacy.py

候选敏感字段服务端裁剪（总册 22.2/12.5）。

角色字段视图：
- RECRUITER（招聘管理员）：常规字段 + 联系方式（手机号遮罩）
- QUALIFICATION_REVIEWER：资格所需字段，不含高敏 PII
- EXPERT（专家）：盲评时仅候选编号 + 必要材料，隐藏姓名/联系方式
- HIRING_MANAGER：必要候选信息，不看高敏 PII
- AUDITOR：只读审计，无 PII 明文
- SELF（候选人本人）：本人全字段

原则：
- 服务端裁剪，不是 CSS 隐藏。
- 手机号遮罩：保留前 3 后 4（138****1234）。
- 身份证/简历正文默认不进 API。
"""

from __future__ import annotations

# 角色 → 可见字段集合（服务端裁剪）
ROLE_VISIBLE_FIELDS = {
    "SELF": {
        "legal_name",
        "preferred_name",
        "primary_email",
        "primary_mobile",
        "national_id_cipher",  # 本人可见（加密态展示由服务端处理）
        "national_id_hash",
        "date_of_birth",
        "gender",
        "address",
        "consent_version",
        "consent_at",
        "retention_until",
        "source",
        "status",
    },
    "RECRUITER": {
        "legal_name",
        "preferred_name",
        "primary_email",
        "primary_mobile_masked",
        "date_of_birth",
        "gender",
        "source",
        "status",
        "talent_tags",
    },
    "QUALIFICATION_REVIEWER": {
        "legal_name",
        "preferred_name",
        "primary_email",
        "primary_mobile_masked",
        "date_of_birth",
        "gender",
        "source",
    },
    "EXPERT": {
        "candidate_no",
        "legal_name",  # 盲评时被服务端移除（见 mask_blind）
    },
    "HIRING_MANAGER": {
        "legal_name",
        "preferred_name",
        "primary_email",
        "primary_mobile_masked",
    },
    "AUDITOR": {
        "candidate_uid",
        "status",
        "created_at",
    },
}

# 高敏字段：默认不进 API（除非特权 sensitive_view）
HIGH_SENSITIVE_FIELDS = frozenset(
    {"national_id_cipher", "national_id_hash", "resume", "primary_mobile_full"}
)


def mask_mobile(mobile: str | None) -> str | None:
    """手机号遮罩：138****1234。"""
    if not mobile:
        return None
    digits = "".join(ch for ch in mobile if ch.isdigit())
    if len(digits) < 7:
        return "*" * min(len(digits), 4) if digits else None
    return f"{digits[:3]}****{digits[-4:]}"


def visible_fields_for_role(role: str) -> set[str]:
    return ROLE_VISIBLE_FIELDS.get(role, ROLE_VISIBLE_FIELDS["AUDITOR"])


def mask_blind(fields: dict) -> dict:
    """专家盲评：移除姓名/联系方式（服务端裁剪）。"""
    blinded = dict(fields)
    for key in ("legal_name", "preferred_name", "primary_email", "primary_mobile", "primary_mobile_masked"):
        blinded.pop(key, None)
    return blinded


def project_candidate(candidate, *, role: str, blind: bool = False) -> dict:
    """按角色裁剪候选字段（服务端）。"""
    allowed = visible_fields_for_role(role)
    data = {
        "id": str(candidate.id),
        "candidate_uid": candidate.candidate_uid,
        "candidate_no": candidate.candidate_no,
        "legal_name": candidate.legal_name,
        "preferred_name": candidate.preferred_name,
        "primary_email": candidate.primary_email,
        "primary_mobile_masked": mask_mobile(candidate.primary_mobile),
        "source": candidate.source,
        "status": candidate.status,
        "talent_tags": candidate.talent_tags,
        "created_at": candidate.created_at.isoformat() if candidate.created_at else None,
    }
    filtered = {k: v for k, v in data.items() if k in allowed}
    if blind:
        filtered = mask_blind(filtered)
    return filtered
