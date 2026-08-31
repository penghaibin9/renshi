"""
hr_recruitment/jobs/legacy_migrate.py

HR04-S10 legacy Candidate 拆分迁移（总册 30.1）。

匹配键：tenant + identity hash(优先) + email/mobile + name。
输出：EXACT_MATCH / POSSIBLE_MATCH / NO_MATCH / INSUFFICIENT_DATA。
POSSIBLE_MATCH 进人工队列，禁止自动 merge。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class MigrationResult:
    tenant_id: int
    candidates_processed: int = 0
    applications_created: int = 0
    possible_matches: int = 0
    skipped: int = 0
    notes: list = field(default_factory=list)


def migrate_legacy_candidates(*, tenant_id: int, dry_run: bool = True) -> MigrationResult:
    """
    拆分 legacy Candidate → HrRecruitmentCandidate + HrJobApplication。

    V1 仅 dry-run 统计（总控纪律：迁移需人工确认后执行，不自动合并）。
    返回统计结果；非 dry_run 时实际创建。
    """
    from django.apps import apps

    result = MigrationResult(tenant_id=tenant_id)
    if not apps.is_installed("recruitment"):
        result.notes.append("legacy recruitment 未安装，跳过")
        return result

    from recruitment.models import Candidate as LegacyCandidate

    from hr_recruitment.services.candidate_service import CandidateService
    from hr_recruitment.services.application_service import ApplicationService

    candidate_service = CandidateService(tenant_id=tenant_id, actor="migration")
    app_service = ApplicationService(tenant_id=tenant_id, actor="migration")

    legacy_candidates = LegacyCandidate.objects.order_by("id")
    for legacy in legacy_candidates:
        result.candidates_processed += 1
        # identity match（按 email 不做自动合并；无 email 无法可靠匹配）
        match = candidate_service.identity_match(primary_email=legacy.email)
        if match["match_result"] in ("POSSIBLE_MATCH", "EXACT_MATCH"):
            result.possible_matches += 1
            result.notes.append(
                f"legacy #{legacy.id} {legacy.email} 存在 POSSIBLE_MATCH，需人工确认，跳过自动迁移"
            )
            continue
        if not legacy.email:
            result.skipped += 1
            continue
        if dry_run:
            result.notes.append(f"legacy #{legacy.id} {legacy.email} 可迁移（dry-run）")
            continue
        # 实际迁移
        candidate = candidate_service.create_candidate(
            legal_name=legacy.name or "未命名",
            primary_email=legacy.email,
            primary_mobile=legacy.mobile,
            source="LEGACY_MIGRATION",
        )
        draft = app_service.save_draft(
            candidate_id=str(candidate.id),
            recruitment_position_id=_legacy_position_id(legacy),
        )
        app_service.submit(application_id=str(draft.id))
        result.applications_created += 1
    return result


def _legacy_position_id(legacy_candidate):
    """从 legacy Candidate 关联的招聘岗位找 HR04 position（无则 None，走投影）。"""
    from hr_recruitment.models import HrRecruitmentPosition

    if not legacy_candidate.job_position_id_id:
        return None
    position = HrRecruitmentPosition.objects.filter(
        post_catalog_id=legacy_candidate.job_position_id_id
    ).first()
    return str(position.id) if position else None
