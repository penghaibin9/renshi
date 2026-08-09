"""
hr_external/services/compliance_service.py —— 聘用审批前检查（S5，总册 §35/§36/§37/§38/§39/§40）。

检查项（§35）至少：
person identity / external category / source org / ethics declaration / qualification /
required experience / conflict of interest / existing active engagements / overlapping
workload / teaching qualification if needed / target org / task need / agreement policy /
access policy / cost estimate。

输出：每一项 PASS / WARNING / BLOCKER（§35 规则引擎语义；PASS/WARNING/BLOCKER/MANUAL_REVIEW 见 HR07 §26 对齐）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from hr_external.constants import (
    AgreementRequirement,
    ConflictDeclarationStatus,
    EthicsReviewStatus,
    ExternalEngagementStatus,
    IdentityVerificationStatus,
)
from hr_external.models import (
    HrExternalCategory,
    HrExternalConflictDeclaration,
    HrExternalEngagement,
    HrExternalEthicsReview,
    HrExternalHiringCase,
    HrExternalTeacherProfile,
)


@dataclass
class ComplianceCheck:
    code: str
    level: str  # PASS / WARNING / BLOCKER
    message: str


@dataclass
class ComplianceResult:
    checks: list[ComplianceCheck] = field(default_factory=list)

    @property
    def blockers(self) -> list[ComplianceCheck]:
        return [c for c in self.checks if c.level == "BLOCKER"]

    @property
    def has_blocker(self) -> bool:
        return bool(self.blockers)

    def summary(self) -> dict:
        return {
            "blockerCount": len(self.blockers),
            "warningCount": len([c for c in self.checks if c.level == "WARNING"]),
            "passCount": len([c for c in self.checks if c.level == "PASS"]),
            "checks": [
                {"code": c.code, "level": c.level, "message": c.message}
                for c in self.checks
            ],
        }


class ComplianceService:
    """审批前检查（§35）。POSSIBLE 问题绝不静默跳过。"""

    def run_checks(
        self,
        *,
        tenant_id: int,
        case: HrExternalHiringCase,
        profile: HrExternalTeacherProfile,
        category: HrExternalCategory,
    ) -> ComplianceResult:
        checks: list[ComplianceCheck] = []

        # 1) Person identity（§35）
        if profile.identity_verification_status != IdentityVerificationStatus.VERIFIED:
            checks.append(
                ComplianceCheck(
                    "PERSON_IDENTITY",
                    "BLOCKER",
                    "候选人身份未核验（identity_verification_status 非 VERIFIED）",
                )
            )
        else:
            checks.append(ComplianceCheck("PERSON_IDENTITY", "PASS", "身份已核验"))

        # 2) External category 有效性
        if not category.is_active:
            checks.append(
                ComplianceCheck("EXTERNAL_CATEGORY_INVALID", "BLOCKER", "外聘类别已停用")
            )
        else:
            checks.append(ComplianceCheck("EXTERNAL_CATEGORY_INVALID", "PASS", "类别有效"))

        # 3) Ethics declaration（§36）
        ethics = HrExternalEthicsReview.objects.filter(
            tenant_id=tenant_id,
            case_id=case,
            status=EthicsReviewStatus.PASS,
        ).first()
        if category.requires_ethics_review and not ethics:
            checks.append(
                ComplianceCheck(
                    "ETHICS_REVIEW_FAILED",
                    "BLOCKER",
                    "类别要求师德/伦理审查但未通过",
                )
            )
        else:
            checks.append(
                ComplianceCheck("ETHICS_REVIEW_FAILED", "PASS", "伦理审查满足")
            )

        # 4) Conflict declaration（§37）
        conflict = HrExternalConflictDeclaration.objects.filter(
            tenant_id=tenant_id,
            case_id=case,
            status__in=[
                ConflictDeclarationStatus.RESOLVED,
                ConflictDeclarationStatus.DECLARED,
            ],
        ).first()
        if not conflict and category.requires_ethics_review:
            checks.append(
                ComplianceCheck(
                    "EXTERNAL_CONFLICT_REVIEW_REQUIRED",
                    "WARNING",
                    "未找到利益冲突声明（建议补充）",
                )
            )
        else:
            checks.append(ComplianceCheck("EXTERNAL_CONFLICT_REVIEW_REQUIRED", "PASS", "冲突声明满足"))

        # 5) Existing active engagements / overlap（§38）
        overlapping = HrExternalEngagement.objects.filter(
            tenant_id=tenant_id,
            person_id_id=case.proposed_person_id_id,
            status__in=[
                ExternalEngagementStatus.ACTIVE,
                ExternalEngagementStatus.SIGNED_WAITING_EFFECTIVE,
                ExternalEngagementStatus.REVIEW_DUE,
                ExternalEngagementStatus.SUSPENDED,
            ],
        ).exists()
        if overlapping:
            checks.append(
                ComplianceCheck(
                    "EXTERNAL_ENGAGEMENT_OVERLAP",
                    "WARNING",
                    "候选人在该 tenant 已有 active 聘期（需确认并行合规，§21）",
                )
            )
        else:
            checks.append(ComplianceCheck("EXTERNAL_ENGAGEMENT_OVERLAP", "PASS", "无重叠 active 聘期"))

        # 6) 教师资格（按类别要求，§10/§35）
        if category.requires_teacher_qualification and not profile.teacher_qualification_ref:
            checks.append(
                ComplianceCheck(
                    "EXTERNAL_QUALIFICATION_REQUIRED",
                    "BLOCKER",
                    "类别要求教师资格但 profile 无 teacher_qualification_ref",
                )
            )
        else:
            checks.append(ComplianceCheck("EXTERNAL_QUALIFICATION_REQUIRED", "PASS", "教师资格满足"))

        # 7) 行业经历（§28 政策）
        if category.requires_industry_experience and not profile.source_organization_name:
            checks.append(
                ComplianceCheck(
                    "INDUSTRY_EXPERIENCE_REQUIRED",
                    "WARNING",
                    "类别要求行业经历但来源单位为空",
                )
            )
        else:
            checks.append(ComplianceCheck("INDUSTRY_EXPERIENCE_REQUIRED", "PASS", "行业经历满足"))

        # 8) 任务需求（planned_assignments 非空，§32.1）
        if not (case.planned_assignments_json or []):
            checks.append(
                ComplianceCheck("TASK_NEED_MISSING", "WARNING", "未填写拟任任务（planned_assignments）")
            )
        else:
            checks.append(ComplianceCheck("TASK_NEED_MISSING", "PASS", "任务需求已填写"))

        # 9) 协议策略（§42/§93）
        if category.agreement_requirement == AgreementRequirement.REQUIRED_BEFORE_ACTIVATION:
            checks.append(
                ComplianceCheck(
                    "AGREEMENT_REQUIRED",
                    "WARNING",
                    "协议须在激活前签署（HR07 Agreement gate，Provider 占位）",
                )
            )
        else:
            checks.append(ComplianceCheck("AGREEMENT_REQUIRED", "PASS", "协议要求满足"))

        # 10) 预算/成本估计（§101，WARNING 而非 BLOCKER）
        if not case.estimated_cost_reference:
            checks.append(
                ComplianceCheck(
                    "COST_ESTIMATE_MISSING",
                    "WARNING",
                    "未填写成本估计（预算 Provider 未接时仅提示）",
                )
            )
        else:
            checks.append(ComplianceCheck("COST_ESTIMATE_MISSING", "PASS", "成本估计已填"))

        return ComplianceResult(checks)
