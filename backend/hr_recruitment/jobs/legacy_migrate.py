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

    dry_run 只做可迁移性检查；非 dry_run 在已核验身份与岗位映射后实际创建。
    POSSIBLE_MATCH/EXACT_MATCH 一律进入人工确认，禁止自动合并。
    """
    from django.apps import apps
    from django.db import transaction

    result = MigrationResult(tenant_id=tenant_id)
    if not apps.is_installed("recruitment"):
        result.notes.append("legacy recruitment 未安装，跳过")
        return result

    from recruitment.models import Candidate as LegacyCandidate

    from hr_recruitment.services.candidate_service import CandidateService
    from hr_recruitment.services.application_service import ApplicationService

    candidate_service = CandidateService(tenant_id=tenant_id, actor="migration")
    app_service = ApplicationService(tenant_id=tenant_id, actor="migration")

    legacy_candidates = LegacyCandidate.objects.filter(
        recruitment_id__company_id_id=tenant_id
    ).order_by("id")
    for legacy in legacy_candidates:
        result.candidates_processed += 1
        # identity match（按 email 不做自动合并；无 email 无法可靠匹配）
        match = candidate_service.identity_match(primary_email=legacy.email)
        if match["match_result"] in ("POSSIBLE_MATCH", "EXACT_MATCH"):
            result.possible_matches += 1
            result.notes.append(
                f"legacy #{legacy.id} 存在人员匹配候选，需人工确认，跳过自动迁移"
            )
            continue
        if not legacy.email:
            result.skipped += 1
            continue
        recruitment_position_id = _legacy_position_id(legacy, tenant_id=tenant_id)
        if recruitment_position_id is None:
            result.skipped += 1
            result.notes.append(
                f"legacy #{legacy.id} 缺少已核验的 HR02→HR04 岗位映射，跳过"
            )
            continue
        if dry_run:
            result.notes.append(f"legacy #{legacy.id} 可迁移（dry-run）")
            continue
        # 实际迁移
        # 人员、申请、提交必须同事务，避免岗位/提交失败后留下孤立候选人。
        with transaction.atomic():
            candidate = candidate_service.create_candidate(
                legal_name=legacy.name or "未命名",
                primary_email=legacy.email,
                primary_mobile=legacy.mobile,
                source="LEGACY_MIGRATION",
            )
            draft = app_service.save_draft(
                candidate_id=str(candidate.id),
                recruitment_position_id=recruitment_position_id,
            )
            app_service.submit(application_id=str(draft.id))
        result.applications_created += 1
    return result


def _legacy_position_id(legacy_candidate, *, tenant_id: int):
    """经 HR02 正式映射解析 legacy 岗位，禁止把两个域的整数主键直接等同。"""
    from hr_recruitment.models import HrRecruitmentCampaign, HrRecruitmentPosition
    from hr_structure.models import HrLegacyObjectLink

    if not legacy_candidate.job_position_id_id:
        return None
    link = HrLegacyObjectLink.objects.filter(
        tenant_id=tenant_id,
        legacy_app="base",
        legacy_model="jobposition",
        legacy_pk=str(legacy_candidate.job_position_id_id),
        domain_entity_type="position",
        link_status="MAPPED",
    ).first()
    if link is None:
        return None
    try:
        position_id = int(link.domain_entity_id)
    except (TypeError, ValueError):
        return None

    campaign = HrRecruitmentCampaign.objects.filter(
        tenant_id=tenant_id,
        legacy_recruitment_id=legacy_candidate.recruitment_id_id,
    ).first()
    if campaign is None:
        return None
    position = HrRecruitmentPosition.objects.filter(
        tenant_id=tenant_id,
        campaign_id=campaign,
        position_id=position_id,
    ).first()
    return str(position.id) if position else None
