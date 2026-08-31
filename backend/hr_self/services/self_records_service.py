"""SELF-safe file, contract and payslip projections for HR17.

HR17 owns only the experience projection.  HR03, HR07 and HR15 remain the
business authorities and are queried read-only with the resolved SELF identity.
Each source is represented by its own provider envelope so a source outage can
never be mistaken for an empty business collection.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Callable, Optional

from hr_self.services.identity_service import SelfIdentityContext
from hr_self.services.provider_gateway import (
    ProviderStatus,
    SelfProviderRegistry,
    SelfProviderResult,
    default_self_provider_registry,
)


FILES_PROVIDER_VERSION = "hr03.staff-material-self.1"
PROJECTION_VERSION = "hr17.self-records.1"
_VISIBLE_STATUSES = frozenset(
    {
        ProviderStatus.OK,
        ProviderStatus.PARTIAL,
        ProviderStatus.STALE,
        ProviderStatus.NOT_APPLICABLE,
    }
)


def _iso(value):
    return value.isoformat() if value is not None else None


def _identifier(value):
    return str(value) if value is not None else None


def _latest_timestamp(*groups) -> Optional[datetime]:
    timestamps = []
    for group in groups:
        for row in group:
            for field in ("updated_at", "uploaded_at", "created_at"):
                value = getattr(row, field, None)
                if value is not None:
                    timestamps.append(value)
                    break
    return max(timestamps, default=None)


def hr03_controlled_files_provider(context: SelfIdentityContext) -> SelfProviderResult:
    """Read the HR03 material directory without exposing private storage keys.

    A directory row only says which controlled material/version exists.  It
    deliberately excludes ``storage_file_id``, hashes, legacy document IDs and
    uploader/verifier identities.  Actual content access must continue through
    the HR03 short-lived ticket boundary.
    """

    from hr_staff.models import HrStaffMaterial, HrStaffMaterialVersion

    materials = list(
        HrStaffMaterial.objects.filter(
            tenant_id=context.tenant_id,
            staff_id=context.staff_id,
        ).order_by("-updated_at")[:100]
    )
    version_ids = [row.current_version_id for row in materials if row.current_version_id]
    versions = (
        list(
            HrStaffMaterialVersion.objects.filter(
                tenant_id=context.tenant_id,
                id__in=version_ids,
            ).order_by("-version_no")
        )
        if version_ids
        else []
    )
    versions_by_id = {str(row.id): row for row in versions}

    files = []
    for material in materials:
        version = versions_by_id.get(str(material.current_version_id))
        files.append(
            {
                "id": _identifier(material.id),
                "title": material.title,
                "categoryCode": material.category_code,
                "sensitivityLevel": material.sensitivity_level,
                "verificationStatus": material.verification_status,
                "source": material.source or None,
                "relatedFactType": material.related_fact_type or None,
                "updatedAt": _iso(material.updated_at),
                "currentVersion": (
                    {
                        "id": _identifier(version.id),
                        "versionNo": version.version_no,
                        "mimeType": version.mime_type or None,
                        "sizeBytes": version.size_bytes,
                        "issueDate": _iso(version.issue_date),
                        "expiryDate": _iso(version.expiry_date),
                        "status": version.status,
                        "uploadedAt": _iso(version.uploaded_at),
                        "verifiedAt": _iso(version.verified_at),
                        "contentAccess": (
                            "CONTROLLED_TICKET" if version.storage_file_id else "UNAVAILABLE"
                        ),
                    }
                    if version is not None
                    else None
                ),
                "evidence": {
                    "authority": "HR03_STAFF_AUTHORITY",
                    "materialId": _identifier(material.id),
                    "versionId": _identifier(version.id) if version is not None else None,
                    "versionNo": version.version_no if version is not None else None,
                },
            }
        )

    return SelfProviderResult.ok(
        {"files": files},
        source_updated_at=_latest_timestamp(materials, versions),
        provider_version=FILES_PROVIDER_VERSION,
        meta={"scope": "SELF", "authority": "HR03_STAFF_AUTHORITY"},
    )


class SelfRecordsService:
    """Build the three HR17 high-frequency read projections independently."""

    def __init__(
        self,
        context: SelfIdentityContext,
        *,
        registry: Optional[SelfProviderRegistry] = None,
        files_provider: Optional[Callable[[SelfIdentityContext], SelfProviderResult]] = None,
    ):
        if not context or not context.tenant_id or not context.staff_id:
            raise ValueError("resolved SELF identity is required")
        self.context = context
        self.registry = registry or default_self_provider_registry()
        self.files_provider = files_provider or hr03_controlled_files_provider

    def _call_files(self) -> SelfProviderResult:
        try:
            result = self.files_provider(self.context)
        except Exception as exc:
            return SelfProviderResult.error(
                "SOURCE_PROVIDER_ERROR",
                f"HR03 controlled files provider failed: {type(exc).__name__}",
                provider_version=FILES_PROVIDER_VERSION,
            )
        if not isinstance(result, SelfProviderResult):
            return SelfProviderResult.error(
                "SOURCE_PROVIDER_CONTRACT_INVALID",
                "HR03 controlled files provider returned an invalid envelope",
                provider_version=FILES_PROVIDER_VERSION,
            )
        return result

    @staticmethod
    def _validate_collection_result(
        result: SelfProviderResult,
        *,
        collection_key: str,
        source_name: str,
    ) -> SelfProviderResult:
        if result.status not in _VISIBLE_STATUSES:
            return result
        collection = (
            result.data.get(collection_key)
            if isinstance(result.data, Mapping)
            else None
        )
        if not isinstance(collection, list) or any(
            not isinstance(row, Mapping) for row in collection
        ):
            return SelfProviderResult.error(
                "SOURCE_PROVIDER_CONTRACT_INVALID",
                f"{source_name} provider did not return a {collection_key} collection",
                provider_version=result.provider_version,
            )
        return result

    @staticmethod
    def _health(result: SelfProviderResult) -> dict:
        return {
            "status": result.status,
            "sourceUpdatedAt": _iso(result.source_updated_at),
            "errorCode": result.error_code or None,
            "errorMessage": result.error_message or None,
            "providerVersion": result.provider_version,
            "authority": result.meta.get("authority") if result.meta else None,
        }

    @staticmethod
    def _contracts(result: SelfProviderResult):
        if result.status not in _VISIBLE_STATUSES:
            return None
        data = result.data if isinstance(result.data, Mapping) else {}
        rows = data.get("contractAgreements")
        if not isinstance(rows, list):
            rows = []
        return [
            {
                "id": row.get("id"),
                "agreementNo": row.get("agreementNo"),
                "title": row.get("title"),
                "type": row.get("type"),
                "status": row.get("status"),
                "currentVersionNo": row.get("currentVersionNo"),
                "updatedAt": row.get("updatedAt"),
                "evidence": {
                    "authority": "HR07_CONTRACT_AUTHORITY",
                    "agreementId": row.get("id"),
                    "versionNo": row.get("currentVersionNo"),
                    "providerVersion": result.provider_version,
                    "sourceUpdatedAt": _iso(result.source_updated_at),
                },
            }
            for row in rows
        ]

    @staticmethod
    def _payslips(result: SelfProviderResult):
        if result.status not in _VISIBLE_STATUSES:
            return None
        data = result.data if isinstance(result.data, Mapping) else {}
        rows = data.get("payrollResults")
        if not isinstance(rows, list):
            rows = []
        return [
            {
                "id": row.get("id"),
                "resultNo": row.get("resultNo"),
                "periodCode": row.get("periodCode"),
                "currencyCode": row.get("currencyCode"),
                "grossAmount": row.get("grossAmount"),
                "deductionAmount": row.get("deductionAmount"),
                "netAmount": row.get("netAmount"),
                "status": row.get("status"),
                "createdAt": row.get("createdAt"),
                "updatedAt": row.get("updatedAt"),
                "evidence": {
                    "authority": "HR15_PAYROLL_AUTHORITY",
                    "resultId": row.get("id"),
                    "resultNo": row.get("resultNo"),
                    "providerVersion": result.provider_version,
                    "sourceUpdatedAt": _iso(result.source_updated_at),
                },
            }
            for row in rows
            if row.get("status") in {"FINALIZED", "ADJUSTED", "REVERSED"}
        ]

    def build(self) -> dict:
        results = {
            "HR03_FILES": self._call_files(),
            "HR07_CONTRACTS": self.registry.call("HR07", self.context),
            "HR15_PAYSLIPS": self.registry.call("HR15", self.context),
        }
        results["HR03_FILES"] = self._validate_collection_result(
            results["HR03_FILES"],
            collection_key="files",
            source_name="HR03 controlled files",
        )
        results["HR07_CONTRACTS"] = self._validate_collection_result(
            results["HR07_CONTRACTS"],
            collection_key="contractAgreements",
            source_name="HR07 contracts",
        )
        results["HR15_PAYSLIPS"] = self._validate_collection_result(
            results["HR15_PAYSLIPS"],
            collection_key="payrollResults",
            source_name="HR15 payroll",
        )
        files_result = results["HR03_FILES"]
        files = None
        if files_result.status in _VISIBLE_STATUSES:
            data = files_result.data if isinstance(files_result.data, Mapping) else {}
            files = data["files"]

        health = {source: self._health(result) for source, result in results.items()}
        degraded_sources = [
            source
            for source, result in results.items()
            if result.status
            in {
                ProviderStatus.PARTIAL,
                ProviderStatus.UNAVAILABLE,
                ProviderStatus.STALE,
                ProviderStatus.ERROR,
            }
        ]
        return {
            "projectionVersion": PROJECTION_VERSION,
            "files": files,
            "contracts": self._contracts(results["HR07_CONTRACTS"]),
            "payslips": self._payslips(results["HR15_PAYSLIPS"]),
            "sourceHealth": health,
            "degraded": bool(degraded_sources),
            "degradedSources": degraded_sources,
        }
