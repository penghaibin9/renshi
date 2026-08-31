"""HR12 Assessment — Signals（生产级生命周期事件）。"""

from __future__ import annotations

import logging
from typing import Type

from django.db.models.signals import post_save
from django.dispatch import receiver

from hr_assessment.models.case import HrAssessmentCase
from hr_assessment.models.result import HrFinalAssessmentResult

logger = logging.getLogger("hr_assessment.signals")


@receiver(post_save, sender=HrFinalAssessmentResult)
def on_final_result_created(
    sender: Type[HrFinalAssessmentResult],
    instance: HrFinalAssessmentResult,
    created: bool,
    **kwargs,
) -> None:
    """正式结果创建后触发下游事件。

    S10 前仅记录审计日志；S10 集成后对接 Outbox。
    """
    if created and instance.status == "FINALIZED":
        logger.info(
            "AssessmentResultFinalized",
            extra={
                "tenant_id": instance.tenant_id,
                "case_id": str(instance.case_id),
                "assessment_type": instance.assessment_type,
                "grade_code": instance.grade_code,
                "result_version_no": instance.result_version_no,
            },
        )


@receiver(post_save, sender=HrAssessmentCase)
def on_case_status_changed(
    sender: Type[HrAssessmentCase],
    instance: HrAssessmentCase,
    created: bool,
    **kwargs,
) -> None:
    """Case 状态变更审计。"""
    if not created:
        logger.debug(
            "AssessmentCaseStatusChanged",
            extra={
                "tenant_id": instance.tenant_id,
                "case_id": str(instance.id),
                "staff_id": str(instance.staff_id),
                "assessment_type": instance.assessment_type,
                "status": instance.status,
            },
        )
