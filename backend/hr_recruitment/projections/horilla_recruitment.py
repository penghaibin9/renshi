"""
hr_recruitment/projections/horilla_recruitment.py

Horilla Recruitment → HR04 Campaign 投影（只读，总册 28/29）。

原则：
- 投影是只读派生，绝不写 legacy 表；
- Recruitment.vacancy 只作展示值，不是额度权威（HR02 Reservation 权威）；
- stage_type 不作权威 canonical status。
"""

from __future__ import annotations

from hr_recruitment.models import HrRecruitmentCampaign
from hr_recruitment.projections.contracts import LegacyRecruitmentProjection


def project_recruitment_to_campaign(recruitment) -> LegacyRecruitmentProjection:
    """把一条 Horilla Recruitment 投影为展示 DTO。"""
    return LegacyRecruitmentProjection(
        legacy_recruitment_id=recruitment.id,
        title=recruitment.title,
        description=recruitment.description,
        is_event_based=recruitment.is_event_based,
        closed=recruitment.closed,
        is_published=recruitment.is_published,
        vacancy=recruitment.vacancy or 0,
        start_date=recruitment.start_date,
        end_date=recruitment.end_date,
        campaign_id=(
            _find_campaign_id(recruitment)
        ),
        source="LEGACY_RECRUITING_ONLY",
    )


def _find_campaign_id(recruitment):
    """按 legacy_recruitment_id 找已映射的 HR04 campaign。"""
    return (
        HrRecruitmentCampaign.objects.filter(legacy_recruitment_id=recruitment.id)
        .values_list("id", flat=True)
        .first()
    )


def project_recruitments(recruitments) -> list[LegacyRecruitmentProjection]:
    return [project_recruitment_to_campaign(r) for r in recruitments]
