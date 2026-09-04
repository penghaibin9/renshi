"""
hr_recruitment/services/candidate_service.py

HR04-03 候选自然人服务（《04_HR04_总册》§10.3/§23）。

原则：
- 候选人 ≠ 应聘申请；一个候选自然人可有多个 HrJobApplication。
- 禁止仅凭 email 自动合并（§23/§30.1）。
- 去重输出：EXACT_MATCH / POSSIBLE_MATCH / NO_MATCH / INSUFFICIENT_DATA。
- POSSIBLE_MATCH 进人工队列，禁止自动 merge。
- 身份证加密存储 + tenant-scoped hash exact match；不跨租户 dedupe。
"""

from __future__ import annotations

import hashlib
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from hr_recruitment.constants import CandidateStatus, IdentityMatchResult
from hr_recruitment.models import (
    HrCandidateIdentityMatch,
    HrRecruitmentCandidate,
)


def _tenant_scoped_hash(tenant_id: int, national_id: str) -> str:
    """tenant-scoped 身份证 hash（不跨租户 dedupe）。"""
    raw = f"{tenant_id}:{national_id.strip()}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


class CandidateServiceError(Exception):
    def __init__(self, code: str, message: str, *, http_status: int = 422):
        self.code = code
        self.message = message
        self.http_status = http_status
        super().__init__(message)


class CandidateService:
    def __init__(self, *, tenant_id: int, actor: str = ""):
        self.tenant_id = tenant_id
        self.actor = actor

    @transaction.atomic
    def create_candidate(
        self,
        *,
        legal_name,
        preferred_name="",
        primary_email="",
        primary_mobile="",
        national_id=None,
        source="PUBLIC_PORTAL",
        talent_tags=None,
    ) -> HrRecruitmentCandidate:
        """创建候选自然人（candidate_uid immutable；email 只是联系字段）。"""
        candidate_uid = f"c-{uuid4().hex[:12]}"
        while HrRecruitmentCandidate.objects.filter(
            candidate_uid=candidate_uid
        ).exists():
            candidate_uid = f"c-{uuid4().hex[:12]}"

        national_id_hash = (
            _tenant_scoped_hash(self.tenant_id, national_id) if national_id else ""
        )
        candidate = HrRecruitmentCandidate.objects.create(
            tenant_id=self.tenant_id,
            candidate_uid=candidate_uid,
            candidate_no=self._generate_candidate_no(),
            legal_name=legal_name,
            preferred_name=preferred_name,
            primary_email=primary_email,
            primary_mobile=primary_mobile,
            national_id_hash=national_id_hash,
            # 身份证加密由 material/安全层处理；V1 先只存 hash，不存 cipher 明文
            national_id_cipher="",
            source=source,
            talent_tags=talent_tags or [],
            created_by=self.actor,
        )
        try:
            candidate.full_clean()
        except ValidationError as exc:
            raise CandidateServiceError(
                "CANDIDATE_INVALID",
                "; ".join(exc.messages),
            ) from exc
        return candidate

    @transaction.atomic
    def record_consent(
        self,
        candidate_id: str,
        *,
        consent_version: str,
        retention_until,
    ) -> HrRecruitmentCandidate:
        consent_version = str(consent_version or "").strip()
        if not consent_version:
            raise CandidateServiceError("CONSENT_VERSION_REQUIRED", "隐私告知版本不能为空")
        candidate = HrRecruitmentCandidate.objects.select_for_update().filter(
            id=candidate_id,
            tenant_id=self.tenant_id,
            status=CandidateStatus.ACTIVE,
        ).first()
        if candidate is None:
            raise CandidateServiceError(
                "CANDIDATE_NOT_AVAILABLE",
                "候选人不存在或当前不可报名",
                http_status=409,
            )
        candidate.consent_version = consent_version
        candidate.consent_at = timezone.now()
        candidate.retention_until = retention_until
        candidate.save(
            update_fields=[
                "consent_version",
                "consent_at",
                "retention_until",
                "updated_at",
            ]
        )
        from hr_recruitment.models import HrApplicationMaterial

        HrApplicationMaterial.objects.filter(
            tenant_id=self.tenant_id,
            application_id__candidate_id=candidate,
        ).update(retention_until=retention_until)
        return candidate

    def _generate_candidate_no(self) -> str:
        while True:
            no = f"CAN-{uuid4().hex[:8].upper()}"
            if not HrRecruitmentCandidate.objects.filter(
                tenant_id=self.tenant_id, candidate_no=no
            ).exists():
                return no

    def identity_match(
        self, *, legal_name=None, primary_email=None, primary_mobile=None, national_id=None
    ) -> dict:
        """
        去重匹配（§23）。绝不自动 merge。

        匹配键优先级：tenant-scoped identity hash > email > mobile > name。
        """
        match_result = IdentityMatchResult.NO_MATCH
        matches = []

        # 1) identity hash exact（最可信）
        if national_id:
            h = _tenant_scoped_hash(self.tenant_id, national_id)
            by_hash = HrRecruitmentCandidate.objects.filter(
                tenant_id=self.tenant_id, national_id_hash=h
            )
            if by_hash.exists():
                match_result = IdentityMatchResult.EXACT_MATCH
                matches = list(by_hash)
                return self._result(match_result, matches)

        # 2) email exact（仅联系字段，不自动合并）
        if primary_email:
            by_email = HrRecruitmentCandidate.objects.filter(
                tenant_id=self.tenant_id, primary_email__iexact=primary_email
            )
            if by_email.exists():
                match_result = IdentityMatchResult.POSSIBLE_MATCH
                matches = list(by_email)

        # 3) mobile exact
        if not matches and primary_mobile:
            by_mobile = HrRecruitmentCandidate.objects.filter(
                tenant_id=self.tenant_id, primary_mobile=primary_mobile
            )
            if by_mobile.exists():
                match_result = IdentityMatchResult.POSSIBLE_MATCH
                matches = list(by_mobile)

        if not matches:
            match_result = IdentityMatchResult.NO_MATCH
        return self._result(match_result, matches)

    def _result(self, result: str, matches: list) -> dict:
        return {
            "match_result": result,
            "matches": [
                {
                    "id": str(c.id),
                    "candidate_uid": c.candidate_uid,
                    "legal_name": c.legal_name,
                    "primary_email": c.primary_email,
                }
                for c in matches
            ],
            "auto_merge": False,  # 永远禁止自动 merge
        }

    @transaction.atomic
    def record_identity_match(
        self, source_candidate_id: str, target_candidate_id: str | None, match_result: str, basis: dict
    ) -> HrCandidateIdentityMatch:
        """记录去重结果（POSSIBLE_MATCH 进人工队列）。"""
        return HrCandidateIdentityMatch.objects.create(
            tenant_id=self.tenant_id,
            source_candidate_id_id=source_candidate_id,
            target_candidate_id_id=target_candidate_id,
            match_result=match_result,
            match_basis_json=basis,
        )

    @transaction.atomic
    def resolve_match(
        self, match_id: str, *, resolved: bool, resolved_by: str = ""
    ) -> HrCandidateIdentityMatch:
        """人工裁决去重（禁止自动 merge；只有人工可 resolved）。"""
        try:
            match = HrCandidateIdentityMatch.objects.get(
                id=match_id, tenant_id=self.tenant_id
            )
        except HrCandidateIdentityMatch.DoesNotExist:
            raise CandidateServiceError("MATCH_NOT_FOUND", "去重记录不存在", http_status=404)
        match.resolved = resolved
        match.resolved_by = resolved_by or self.actor
        match.save(update_fields=["resolved", "resolved_by"])
        return match
