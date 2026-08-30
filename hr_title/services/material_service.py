"""HR13 review-evidence snapshot lifecycle.

Review materials are frozen evidence for one title application. HR13 records
what reviewers saw and where it came from, but it does not mutate HR03/09/10/12
upstream authority facts. Accepted evidence is immutable; corrections append a
new snapshot instead of rewriting accepted history.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from django.db import transaction
from django.utils import timezone

from hr_title.models import TitleApplicationCase, TitleMaterialSnapshot


class TitleMaterialError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class TitleMaterialInput:
    material_no: str
    application_case_id: object
    material_type: str
    display_name: str
    content_hash: str
    source_domain: str = "SELF"
    source_ref: str = ""
    source_version: str = ""
    snapshot_json: dict = field(default_factory=dict)
    supersedes_snapshot_id: object | None = None


class TitleMaterialService:
    ATTACHABLE_CASE_STATES = frozenset(
        {
            TitleApplicationCase.Status.DRAFT,
            TitleApplicationCase.Status.RETURNED,
            TitleApplicationCase.Status.SUBMITTED,
            TitleApplicationCase.Status.ELIGIBLE,
        }
    )

    def __init__(self, tenant_id: int, actor_user_id: Optional[int] = None):
        if not tenant_id:
            raise TitleMaterialError("TENANT_CONTEXT_REQUIRED", "tenant_id is required")
        self.tenant_id = int(tenant_id)
        self.actor_user_id = actor_user_id

    def _lock_case(self, case_id) -> TitleApplicationCase:
        case = (
            TitleApplicationCase.objects.select_for_update()
            .filter(id=case_id, tenant_id=self.tenant_id)
            .first()
        )
        if case is None:
            raise TitleMaterialError("TITLE_CASE_NOT_FOUND", "application case not found")
        return case

    def _get_case(self, case_id) -> TitleApplicationCase:
        case = TitleApplicationCase.objects.filter(
            id=case_id, tenant_id=self.tenant_id
        ).first()
        if case is None:
            raise TitleMaterialError("TITLE_CASE_NOT_FOUND", "application case not found")
        return case

    def _lock_material(self, material_id) -> TitleMaterialSnapshot:
        material = (
            TitleMaterialSnapshot.objects.select_for_update()
            .filter(id=material_id, tenant_id=self.tenant_id)
            .first()
        )
        if material is None:
            raise TitleMaterialError("TITLE_MATERIAL_NOT_FOUND", "material snapshot not found")
        return material

    @staticmethod
    def _normalize(payload: TitleMaterialInput) -> dict:
        values = {
            "material_no": (payload.material_no or "").strip(),
            "material_type": (payload.material_type or "").strip(),
            "display_name": (payload.display_name or "").strip(),
            "content_hash": (payload.content_hash or "").strip(),
            "source_domain": (payload.source_domain or "SELF").strip().upper(),
            "source_ref": (payload.source_ref or "").strip(),
            "source_version": (payload.source_version or "").strip(),
        }
        if not all(
            values[key]
            for key in ("material_no", "material_type", "display_name", "content_hash")
        ):
            raise TitleMaterialError(
                "TITLE_MATERIAL_REQUIRED_FIELDS",
                "material_no, material_type, display_name and content_hash are required",
            )
        if not isinstance(payload.snapshot_json, dict):
            raise TitleMaterialError(
                "TITLE_MATERIAL_SNAPSHOT_INVALID", "snapshot_json must be an object"
            )
        return values

    @staticmethod
    def _content_hash(snapshot: dict) -> str:
        raw = json.dumps(
            snapshot,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @transaction.atomic
    def attach_hr12_final_assessment(
        self,
        *,
        application_case_id,
        assessment_result_id,
        material_no: str,
        as_of: date | None = None,
    ) -> TitleMaterialSnapshot:
        """Attach one HR12 FINALIZED result through the trusted source boundary.

        Callers provide only identities. HR13 derives the authoritative snapshot
        from HR12 and refuses tenant/person/as-of/version mismatches instead of
        trusting arbitrary ``source_domain=HR12`` JSON from the request layer.
        """

        from hr_assessment.public import (
            PROVIDER_VERSION,
            AssessmentEvidenceUnavailable,
            get_finalized_assessment_evidence,
            record_result_application,
        )

        case = self._get_case(application_case_id)
        try:
            evidence = get_finalized_assessment_evidence(
                tenant_id=self.tenant_id,
                person_id=case.person_id,
                result_id=assessment_result_id,
                as_of=as_of or timezone.localdate(),
                source_version=PROVIDER_VERSION,
            )
        except AssessmentEvidenceUnavailable as exc:
            raise TitleMaterialError(exc.code, str(exc)) from exc

        snapshot = evidence.snapshot()
        content_hash = evidence.content_hash or self._content_hash(snapshot)
        material = self.attach_snapshot(
            TitleMaterialInput(
                material_no=material_no,
                application_case_id=case.id,
                material_type="HR12_FINAL_ASSESSMENT",
                display_name=(
                    f"正式考核结果（{evidence.assessment_type}/{evidence.grade_code}）"
                ),
                content_hash=content_hash,
                source_domain="HR12",
                source_ref=str(evidence.result_id),
                source_version=evidence.source_version,
                snapshot_json=snapshot,
            )
        )
        try:
            record_result_application(
                tenant_id=self.tenant_id,
                evidence=evidence,
                consumer_domain="HR13",
                consumer_object_id=material.id,
                purpose="PROFESSIONAL_TITLE_MATERIAL",
            )
        except AssessmentEvidenceUnavailable as exc:
            raise TitleMaterialError(exc.code, str(exc)) from exc
        return material

    @transaction.atomic
    def attach_snapshot(self, payload: TitleMaterialInput) -> TitleMaterialSnapshot:
        values = self._normalize(payload)
        case = self._lock_case(payload.application_case_id)
        if case.status not in self.ATTACHABLE_CASE_STATES:
            raise TitleMaterialError(
                "TITLE_MATERIAL_CASE_NOT_ATTACHABLE",
                f"case status {case.status} cannot accept new review evidence",
            )

        existing = (
            TitleMaterialSnapshot.objects.select_for_update()
            .filter(tenant_id=self.tenant_id, material_no=values["material_no"])
            .first()
        )
        if existing is not None:
            same_request = (
                existing.application_case_id == case.id
                and existing.material_type == values["material_type"]
                and existing.display_name == values["display_name"]
                and existing.content_hash == values["content_hash"]
                and existing.source_domain == values["source_domain"]
                and existing.source_ref == values["source_ref"]
                and existing.source_version == values["source_version"]
                and existing.snapshot_json == payload.snapshot_json
                and existing.supersedes_snapshot_id == payload.supersedes_snapshot_id
            )
            if not same_request:
                raise TitleMaterialError(
                    "TITLE_MATERIAL_IDEMPOTENCY_CONFLICT",
                    "material_no already belongs to a different evidence snapshot",
                )
            return existing

        if payload.supersedes_snapshot_id is not None:
            previous = self._lock_material(payload.supersedes_snapshot_id)
            if previous.application_case_id != case.id:
                raise TitleMaterialError(
                    "TITLE_MATERIAL_SUPERSEDES_CASE_MISMATCH",
                    "replacement evidence must belong to the same application case",
                )
            if previous.status != TitleMaterialSnapshot.Status.RETURNED:
                raise TitleMaterialError(
                    "TITLE_MATERIAL_SUPERSEDES_INVALID_STATE",
                    "only returned evidence may be replaced by a new snapshot",
                )

        return TitleMaterialSnapshot.objects.create(
            tenant_id=self.tenant_id,
            application_case_id=case.id,
            material_no=values["material_no"],
            material_type=values["material_type"],
            display_name=values["display_name"],
            source_domain=values["source_domain"],
            source_ref=values["source_ref"],
            source_version=values["source_version"],
            content_hash=values["content_hash"],
            snapshot_json=dict(payload.snapshot_json),
            status=TitleMaterialSnapshot.Status.ATTACHED,
            supersedes_snapshot_id=payload.supersedes_snapshot_id,
            created_by=self.actor_user_id,
            updated_by=self.actor_user_id,
        )

    @transaction.atomic
    def return_for_correction(self, material_id) -> TitleMaterialSnapshot:
        material = self._lock_material(material_id)
        if material.status == TitleMaterialSnapshot.Status.RETURNED:
            return material
        if material.status != TitleMaterialSnapshot.Status.ATTACHED:
            raise TitleMaterialError(
                "TITLE_MATERIAL_INVALID_STATE",
                f"material status {material.status} cannot be returned",
            )
        material.status = TitleMaterialSnapshot.Status.RETURNED
        material.updated_by = self.actor_user_id
        material.save(update_fields=["status", "updated_by", "updated_at"])
        return material

    @transaction.atomic
    def accept(self, material_id) -> TitleMaterialSnapshot:
        material = self._lock_material(material_id)
        if material.status == TitleMaterialSnapshot.Status.ACCEPTED:
            return material
        if material.status != TitleMaterialSnapshot.Status.ATTACHED:
            raise TitleMaterialError(
                "TITLE_MATERIAL_INVALID_STATE",
                f"material status {material.status} cannot be accepted",
            )
        material.status = TitleMaterialSnapshot.Status.ACCEPTED
        material.updated_by = self.actor_user_id
        material.save(update_fields=["status", "updated_by", "updated_at"])
        return material

    @transaction.atomic
    def withdraw(self, material_id) -> TitleMaterialSnapshot:
        material = self._lock_material(material_id)
        if material.status == TitleMaterialSnapshot.Status.WITHDRAWN:
            return material
        if material.status not in {
            TitleMaterialSnapshot.Status.ATTACHED,
            TitleMaterialSnapshot.Status.RETURNED,
        }:
            raise TitleMaterialError(
                "TITLE_MATERIAL_INVALID_STATE",
                f"material status {material.status} cannot be withdrawn",
            )
        material.status = TitleMaterialSnapshot.Status.WITHDRAWN
        material.updated_by = self.actor_user_id
        material.save(update_fields=["status", "updated_by", "updated_at"])
        return material
