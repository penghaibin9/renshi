"""
hr_recruitment/jobs/dual_read_compare.py

HR04-S10 DUAL_READ_COMPARE（总册 29.2/30）。

新旧同时计算：
  campaign / applications / candidate counts / stage mapping / hired / interview
→ 生成 discrepancy report。

禁止"哪边有值用哪边"；discrepancy 必须可审。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from django.db.models import Count


@dataclass
class DiscrepancyReport:
    tenant_id: int
    mode: str = "DUAL_READ_COMPARE"
    discrepancies: list = field(default_factory=list)
    metrics: dict = field(default_factory=dict)

    def add(self, dimension: str, legacy_value, authority_value, note=""):
        self.discrepancies.append(
            {
                "dimension": dimension,
                "legacy_value": legacy_value,
                "authority_value": authority_value,
                "note": note,
            }
        )


def run_dual_read_compare(*, tenant_id: int) -> DiscrepancyReport:
    """
    新旧对账（V1 最小实现：legacy recruitment.Candidate/Recruitment vs HR04）。

    返回 discrepancy 列表；调用方负责持久化/展示。
    """
    from django.apps import apps

    report = DiscrepancyReport(tenant_id=tenant_id)

    if not apps.is_installed("recruitment"):
        report.add("recruitment_app", "未安装", "—", "legacy recruitment 未安装，跳过对账")
        return report

    from recruitment.models import Candidate as LegacyCandidate
    from recruitment.models import Recruitment as LegacyRecruitment

    from hr_recruitment.models import HrJobApplication, HrRecruitmentCampaign

    # 1) Campaign 映射覆盖
    legacy_rec_count = LegacyRecruitment.objects.count()
    mapped_campaigns = HrRecruitmentCampaign.objects.filter(
        tenant_id=tenant_id, legacy_recruitment_id__isnull=False
    ).count()
    report.metrics["legacy_recruitments"] = legacy_rec_count
    report.metrics["mapped_campaigns"] = mapped_campaigns
    if legacy_rec_count and mapped_campaigns < legacy_rec_count:
        report.add(
            "campaign_mapping",
            legacy_rec_count,
            mapped_campaigns,
            "存在未映射到 HR04 campaign 的 legacy Recruitment",
        )

    # 2) Candidate / Application 计数
    legacy_cand_count = LegacyCandidate.objects.count()
    authority_app_count = HrJobApplication.objects.filter(tenant_id=tenant_id).count()
    report.metrics["legacy_candidates"] = legacy_cand_count
    report.metrics["authority_applications"] = authority_app_count

    # 3) hired 计数（legacy 不权威）
    legacy_hired = LegacyCandidate.objects.filter(hired=True).count()
    authority_handoff = HrJobApplication.objects.filter(
        tenant_id=tenant_id, canonical_status="HANDOFF_TO_HR05"
    ).count()
    report.metrics["legacy_hired"] = legacy_hired
    report.metrics["authority_handoff"] = authority_handoff
    if legacy_hired != authority_handoff:
        report.add(
            "hired_vs_handoff",
            legacy_hired,
            authority_handoff,
            "legacy hired 与 HR04 HANDOFF_TO_HR05 不一致（legacy 非权威，需人工裁决）",
        )

    return report
