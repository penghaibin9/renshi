"""
hr10_development/services/completion_service.py

培训完成核验服务（总册 §55/§67）。

VERIFIED 后不可原地修改；纠错走 revision_no + supersedes_id。
只有满足 policy 的核验结果才生成 DevelopmentFact。
"""

import hashlib
import json
from datetime import datetime, timezone

from django.db import transaction

from hr10_development.constants import VerificationStatus, CompletionStatus


class CompletionService:
    """培训完成核验。"""

    # 可进入 VERIFIED 的核验来源（总册 §67）
    VERIFIABLE_SOURCES = (
        VerificationStatus.SYSTEM_PROVIDER_VERIFIED,
        VerificationStatus.TRAINING_PROVIDER_VERIFIED,
        VerificationStatus.INTERNAL_INSTRUCTOR_VERIFIED,
        VerificationStatus.HR_VERIFIED,
        VerificationStatus.DOCUMENT_VERIFIED,
        VerificationStatus.MANUAL_COMMITTEE_VERIFIED,
    )

    @staticmethod
    def _lock_completion(completion):
        return type(completion).objects.select_for_update().get(
            pk=completion.pk,
            tenant_id=completion.tenant_id,
        )

    @staticmethod
    @transaction.atomic
    def submit_completion(completion, submitted_evidence_package_id: str) -> dict:
        """提交完成核验申请。"""
        completion = CompletionService._lock_completion(completion)
        if completion.verification_status in CompletionService.VERIFIABLE_SOURCES:
            return {"status": "ALREADY_VERIFIED"}

        completion.evidence_package_id = submitted_evidence_package_id
        completion.completion_status = CompletionStatus.PASS
        completion.save(update_fields=["evidence_package_id", "completion_status", "updated_at"])
        return {"status": "SUBMITTED"}

    @staticmethod
    @transaction.atomic
    def verify_completion(completion, verifier_id: int, verification_source: str) -> dict:
        """
        核验完成。

        Only VERIFIED → generate DevelopmentFact。
        已核验记录不可原地修改。
        """
        completion = CompletionService._lock_completion(completion)
        if completion.verification_status in CompletionService.VERIFIABLE_SOURCES:
            return {"status": "COMPLETION_ALREADY_VERIFIED"}

        if verification_source not in CompletionService.VERIFIABLE_SOURCES:
            return {"status": "INVALID_VERIFICATION_SOURCE"}

        # VERIFIED 后不可原地改 → 通过 revision 更新
        if completion.immutable_hash:
            return {"status": "COMPLETION_REVISION_REQUIRED"}

        completion.verification_status = verification_source
        completion.verified_by = verifier_id
        completion.verified_at = datetime.now(timezone.utc)
        completion.immutable_hash = CompletionService._immutable_hash(completion)
        completion.save(update_fields=[
            "verification_status", "verified_by", "verified_at", "immutable_hash", "updated_at",
        ])

        # 生成 DevelopmentFact
        from hr10_development.services.development_fact_service import DevelopmentFactService
        fact = DevelopmentFactService.generate_fact_from_completion(
            completion=completion,
            tenant_id=completion.tenant_id,
        )

        return {"status": "VERIFIED", "factId": str(fact.id) if fact else None}

    @staticmethod
    def _immutable_hash(completion) -> str:
        raw = json.dumps({
            "id": str(completion.id),
            "enrollment_id": str(completion.enrollment_id),
            "verified_hours": str(completion.verified_hours),
            "verification_status": completion.verification_status,
        }, sort_keys=True)
        return hashlib.sha256(raw.encode()).hexdigest()
