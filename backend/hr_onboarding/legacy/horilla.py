"""HR05 对 Horilla onboarding 的迁移期只读 adapter。

旧 OnboardingStage/CandidateStage/CandidateTask 可以作为迁移和对账来源，
但不能直接成为 HR05 新 OnboardingCase/Task Authority。所有读取显式 tenant scope。
"""

from __future__ import annotations


def _candidate_stage_model():
    from onboarding.models import CandidateStage

    return CandidateStage


def _candidate_task_model():
    from onboarding.models import CandidateTask

    return CandidateTask


class HorillaLegacyOnboardingAdapter:
    def __init__(self, tenant_id: int):
        if not tenant_id:
            raise ValueError("tenant_id is required")
        self.tenant_id = tenant_id

    def get_candidate_stage(self, *, legacy_candidate_id: int) -> dict | None:
        CandidateStage = _candidate_stage_model()
        row = (
            CandidateStage.objects.filter(
                candidate_id_id=legacy_candidate_id,
                candidate_id__recruitment_id__company_id=self.tenant_id,
            )
            .values(
                "id",
                "candidate_id_id",
                "onboarding_stage_id_id",
                "onboarding_stage_id__stage_title",
                "sequence",
                "onboarding_end_date",
            )
            .first()
        )
        if row is None:
            return None
        return {
            **row,
            "source": "legacy.onboarding.CandidateStage",
            "authority": False,
        }

    def list_candidate_tasks(self, *, legacy_candidate_id: int) -> list[dict]:
        CandidateTask = _candidate_task_model()
        rows = CandidateTask.objects.filter(
            candidate_id_id=legacy_candidate_id,
            candidate_id__recruitment_id__company_id=self.tenant_id,
        ).values(
            "id",
            "candidate_id_id",
            "stage_id_id",
            "onboarding_task_id_id",
            "onboarding_task_id__task_title",
            "onboarding_task_id__is_required",
            "status",
        )
        return [
            {
                **row,
                "source": "legacy.onboarding.CandidateTask",
                "legacyStatus": row.get("status"),
                "authority": False,
            }
            for row in rows
        ]
