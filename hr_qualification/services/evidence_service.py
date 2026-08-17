"""
hr_qualification/services/evidence_service.py —— 证据聚合服务（总册 §59/§63/§116）。

- 多源证据聚合（HR03/HR08/HR09/HR10/Academic）
- 统一 as_of 快照
- EvidencePackage 生成 + 冻结
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date, datetime

from django.db import transaction

from hr_qualification.constants import EvidencePackageStatus
from hr_qualification.models import (
    HrDoubleTeacherApplication,
    HrDoubleTeacherEvidenceItem,
    HrDoubleTeacherEvidencePackage,
    HrDoubleTeacherEvidenceRequirement,
)
from hr_qualification.providers.base import ProviderEvidenceItem, ProviderEvidenceResult


class EvidenceAggregationService:
    """证据聚合服务。"""

    def __init__(self, providers: list = None):
        if providers is None:
            self._providers = self._default_providers()
        else:
            self._providers = providers

    @staticmethod
    def _default_providers() -> list:
        """构建默认 Provider 集。未就绪的返回 UNAVAILABLE（不静默 fallback）。"""
        from hr_qualification.providers.hr03 import Hr03EducationProvider, Hr03WorkHistoryProvider
        from hr_qualification.providers.hr08 import Hr08EngagementProvider
        from hr_qualification.providers.hr10 import Hr10EnterprisePracticeProvider, Hr10TrainingProvider, AcademicTeachingProvider
        return [
            Hr03EducationProvider(),
            Hr03WorkHistoryProvider(),
            Hr08EngagementProvider(),
            Hr10EnterprisePracticeProvider(),
            Hr10TrainingProvider(),
            AcademicTeachingProvider(),
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
        """调用所有注册 Provider 聚合证据。

        Returns:
            {provider_key: ProviderEvidenceResult}
        """
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
                    errors=[{"code": "PROVIDER_EXCEPTION", "message": str(exc)}],
                )
            results[provider.provider_key] = result
        return results

    def build_package(
        self,
        application: HrDoubleTeacherApplication,
        requirements: list[HrDoubleTeacherEvidenceRequirement],
        as_of: date | None = None,
    ) -> HrDoubleTeacherEvidencePackage:
        """为申报构建 EvidencePackage（提交时冻结）。"""
        as_of = as_of or date.today()

        # 聚合所有 Provider
        results = self.aggregate(
            person_id=application.person_id_id,
            staff_master_id=application.staff_master_id_id,
            tenant_id=application.tenant_id,
            as_of=as_of,
        )

        with transaction.atomic():
            package = HrDoubleTeacherEvidencePackage.objects.create(
                application_id=application,
                rule_pack_version_id=application.batch_id.rule_pack_version_id,
                source_snapshots_json={
                    k: {"status": v.status, "items_count": len(v.items)}
                    for k, v in results.items()
                },
                status=EvidencePackageStatus.GENERATED,
            )

            # 按 requirement 对证据分类
            for req in requirements:
                for _, result in results.items():
                    for item in result.items:
                        # 匹配规则要求的证据来源域
                        if req.allowed_source_domains and item.source_domain not in (
                            req.allowed_source_domains or []
                        ):
                            continue

                        HrDoubleTeacherEvidenceItem.objects.create(
                            package_id=package,
                            requirement_id=req,
                            source_domain=item.source_domain,
                            source_object_type=item.source_object_type,
                            source_object_id=item.source_object_id,
                            evidence_date=item.evidence_date,
                            title=item.title,
                            role=item.role,
                            quantitative_value=item.quantitative_value,
                            verification_status=item.verification_status,
                            document_refs=item.document_refs or [],
                            snapshot_json=item.snapshot_json,
                        )

            # 计算 checksum
            items = list(
                HrDoubleTeacherEvidenceItem.objects
                .filter(package_id=package)
                .values_list("source_domain", "source_object_id", "title")
                .order_by("source_domain")
            )
            package.checksum = hashlib.sha256(
                json.dumps(items, sort_keys=True, default=str).encode()
            ).hexdigest()
            package.status = EvidencePackageStatus.GENERATED
            package.save()

        return package

    @staticmethod
    def freeze_package(package: HrDoubleTeacherEvidencePackage) -> HrDoubleTeacherEvidencePackage:
        """提交后冻结证据包（不可变）+ 写入 EvidenceUsage 反向引用图。"""
        if package.status == EvidencePackageStatus.FROZEN:
            return package

        with transaction.atomic():
            package.status = EvidencePackageStatus.FROZEN
            package.save()

            # 为每个 EvidenceItem 创建 HrEvidenceUsage 反向引用
            from hr_qualification.models import HrEvidenceUsage
            from hr_qualification.models.evidence import HrDoubleTeacherEvidenceItem

            evidence_items = list(
                HrDoubleTeacherEvidenceItem.objects.filter(package_id=package)
            )

            for item in evidence_items:
                usage_data = {
                    "evidence_type": item.source_domain,
                    "evidence_ref": f"{item.source_object_type}:{item.source_object_id}",
                    "application_id": package.application_id,
                    "rule_id": item.requirement_id.rule_id if item.requirement_id_id else None,
                    "recognition_id": None,
                    "snapshot_hash": package.checksum,
                }

                if not HrEvidenceUsage.objects.filter(
                    evidence_type=usage_data["evidence_type"],
                    evidence_ref=usage_data["evidence_ref"],
                    application_id=usage_data["application_id"],
                ).exists():
                    HrEvidenceUsage.objects.create(**usage_data)

        return package
