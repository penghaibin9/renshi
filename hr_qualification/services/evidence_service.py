"""HR09 evidence aggregation, immutable snapshotting and checksum enforcement."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date
from decimal import Decimal

from django.db import transaction

from hr_qualification.constants import EvidencePackageStatus, EvidenceSourceDomain
from hr_qualification.models import (
    HrDoubleTeacherApplication,
    HrDoubleTeacherEvidenceItem,
    HrDoubleTeacherEvidencePackage,
    HrDoubleTeacherEvidenceRequirement,
)
from hr_qualification.providers.base import (
    ProviderError,
    ProviderEvidenceItem,
    ProviderEvidenceResult,
)


class EvidenceAggregationError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


class EvidenceAggregationService:
    """多源证据聚合服务。"""

    def __init__(self, providers: list | None = None):
        self._providers = self._default_providers() if providers is None else providers

    @staticmethod
    def _default_providers() -> list:
        """All modeled source providers participate; unconfigured sources fail closed."""
        from hr_qualification.providers.hr03 import (
            Hr03EducationProvider,
            Hr03WorkHistoryProvider,
        )
        from hr_qualification.providers.hr08 import Hr08EngagementProvider
        from hr_qualification.providers.hr09 import Hr09CredentialProvider
        from hr_qualification.providers.hr10 import (
            AcademicTeachingProvider,
            Hr10EnterprisePracticeProvider,
            Hr10TrainingProvider,
        )
        from hr_qualification.providers.hr12 import (
            Hr12AssessmentProvider,
            ResearchProjectProvider,
        )

        return [
            Hr03EducationProvider(),
            Hr03WorkHistoryProvider(),
            Hr08EngagementProvider(),
            Hr09CredentialProvider(),
            Hr10EnterprisePracticeProvider(),
            Hr10TrainingProvider(),
            AcademicTeachingProvider(),
            Hr12AssessmentProvider(),
            ResearchProjectProvider(),
        ]

    def register(self, provider) -> None:
        self._providers.append(provider)

    def aggregate(
        self,
        person_id: uuid.UUID,
        staff_master_id: uuid.UUID | None,
        tenant_id: int,
        as_of: date,
    ) -> dict[str, ProviderEvidenceResult]:
        results: dict[str, ProviderEvidenceResult] = {}
        for provider in self._providers:
            try:
                result = provider.provide(
                    person_id=person_id,
                    staff_master_id=staff_master_id,
                    tenant_id=tenant_id,
                    as_of=as_of,
                )
            except Exception as exc:
                result = ProviderEvidenceResult(
                    status="ERROR",
                    errors=[
                        ProviderError(
                            code="PROVIDER_EXCEPTION",
                            message=str(exc)[:1000],
                        )
                    ],
                    provider_version="",
                )
            results[provider.provider_key] = result
        return results

    @staticmethod
    def _provider_snapshot(result: ProviderEvidenceResult) -> dict:
        return {
            "status": str(result.status),
            "itemsCount": len(result.items),
            "providerVersion": result.provider_version or "",
            "sourceUpdatedAt": (
                result.source_updated_at.isoformat()
                if result.source_updated_at is not None
                else None
            ),
            "errors": [
                {
                    "code": getattr(error, "code", "PROVIDER_ERROR"),
                    "message": str(getattr(error, "message", error))[:1000],
                }
                for error in result.errors
            ],
        }

    @staticmethod
    def _item_matches_requirement(
        item: ProviderEvidenceItem,
        requirement: HrDoubleTeacherEvidenceRequirement,
    ) -> bool:
        allowed = requirement.allowed_source_domains or []
        if allowed:
            return item.source_domain in set(allowed)
        # If the requirement itself names a concrete source domain, it is an
        # implicit source restriction. This prevents unrelated provider items
        # from satisfying every requirement when allowed_source_domains is blank.
        if requirement.evidence_category in set(EvidenceSourceDomain.values):
            return item.source_domain == requirement.evidence_category
        return True

    @staticmethod
    def _evidence_item_payload(item: HrDoubleTeacherEvidenceItem) -> dict:
        return {
            "requirementId": str(item.requirement_id_id) if item.requirement_id_id else None,
            "sourceDomain": item.source_domain,
            "sourceObjectType": item.source_object_type,
            "sourceObjectId": item.source_object_id,
            "evidenceDate": item.evidence_date.isoformat() if item.evidence_date else None,
            "title": item.title,
            "role": item.role,
            "quantitativeValue": (
                str(item.quantitative_value) if item.quantitative_value is not None else None
            ),
            "verificationStatus": item.verification_status,
            "documentRefs": item.document_refs or [],
            "snapshot": item.snapshot_json or {},
        }

    @classmethod
    def compute_package_checksum(cls, package: HrDoubleTeacherEvidencePackage) -> str:
        snapshots = package.source_snapshots_json or {}
        items = list(
            HrDoubleTeacherEvidenceItem.objects.filter(package_id=package)
            .select_related("requirement_id")
            .order_by("requirement_id_id", "source_domain", "source_object_type", "source_object_id", "id")
        )
        payload = {
            "applicationId": str(package.application_id_id),
            "rulePackVersionId": str(package.rule_pack_version_id_id),
            "sourceSnapshots": snapshots,
            "items": [cls._evidence_item_payload(item) for item in items],
        }
        return hashlib.sha256(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        ).hexdigest()

    def build_package(
        self,
        application: HrDoubleTeacherApplication,
        requirements: list[HrDoubleTeacherEvidenceRequirement],
        as_of: date | None = None,
    ) -> HrDoubleTeacherEvidencePackage:
        as_of = as_of or date.today()
        results = self.aggregate(
            person_id=application.person_id_id,
            staff_master_id=application.staff_master_id_id,
            tenant_id=application.tenant_id,
            as_of=as_of,
        )
        source_snapshots = {
            "_meta": {
                "asOf": as_of.isoformat(),
                "providerCount": len(results),
            },
            **{
                key: self._provider_snapshot(value)
                for key, value in sorted(results.items())
            },
        }

        with transaction.atomic():
            package = HrDoubleTeacherEvidencePackage.objects.create(
                application_id=application,
                rule_pack_version_id=application.batch_id.rule_pack_version_id,
                source_snapshots_json=source_snapshots,
                status=EvidencePackageStatus.GENERATED,
            )

            seen: set[tuple[str, str, str, str]] = set()
            for requirement in requirements:
                for result in results.values():
                    for item in result.items:
                        if not self._item_matches_requirement(item, requirement):
                            continue
                        dedup_key = (
                            str(requirement.id),
                            item.source_domain,
                            item.source_object_type,
                            item.source_object_id,
                        )
                        if dedup_key in seen:
                            continue
                        seen.add(dedup_key)
                        HrDoubleTeacherEvidenceItem.objects.create(
                            package_id=package,
                            requirement_id=requirement,
                            source_domain=item.source_domain,
                            source_object_type=item.source_object_type,
                            source_object_id=item.source_object_id,
                            evidence_date=item.evidence_date,
                            title=item.title,
                            role=item.role,
                            quantitative_value=(
                                Decimal(str(item.quantitative_value))
                                if item.quantitative_value is not None
                                else None
                            ),
                            verification_status=item.verification_status,
                            document_refs=item.document_refs or [],
                            snapshot_json=item.snapshot_json,
                        )

            package.checksum = self.compute_package_checksum(package)
            package.save(update_fields=["checksum"])
        return package

    @classmethod
    @transaction.atomic
    def freeze_package(
        cls,
        package: HrDoubleTeacherEvidencePackage,
    ) -> HrDoubleTeacherEvidencePackage:
        package = HrDoubleTeacherEvidencePackage.objects.select_for_update().get(id=package.id)
        current_checksum = cls.compute_package_checksum(package)
        if not package.checksum or current_checksum != package.checksum:
            raise EvidenceAggregationError(
                "EVIDENCE_PACKAGE_CHECKSUM_MISMATCH",
                "evidence package changed after generation; rebuild it before freezing",
            )
        if package.status == EvidencePackageStatus.FROZEN:
            return package
        if package.status != EvidencePackageStatus.GENERATED:
            raise EvidenceAggregationError(
                "EVIDENCE_PACKAGE_INVALID_STATE",
                f"package status {package.status} cannot be frozen",
            )

        package.status = EvidencePackageStatus.FROZEN
        package.save(update_fields=["status"])

        from hr_qualification.models import HrEvidenceUsage

        evidence_items = list(
            HrDoubleTeacherEvidenceItem.objects.filter(package_id=package)
        )
        for item in evidence_items:
            evidence_type = item.source_domain
            evidence_ref = f"{item.source_object_type}:{item.source_object_id}"
            if not HrEvidenceUsage.objects.filter(
                evidence_type=evidence_type,
                evidence_ref=evidence_ref,
                application_id=package.application_id,
            ).exists():
                HrEvidenceUsage.objects.create(
                    evidence_type=evidence_type,
                    evidence_ref=evidence_ref,
                    application_id=package.application_id,
                    rule_id=(
                        item.requirement_id.rule_id
                        if item.requirement_id_id
                        else None
                    ),
                    recognition_id=None,
                    snapshot_hash=package.checksum,
                )
        return package
