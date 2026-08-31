"""Evidence-gated takeover of legacy ``report.ReportTemplate`` assets.

Legacy rows are user pivot preferences, not formal HR facts. HR18 records an
immutable inventory/mapping version, requires a real dual-read provider for
every migrated asset, and only blocks legacy writes after all assets are
reconciled or explicitly archived with evidence.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.module_loading import import_string

from hr_data.models import (
    LegacyReportAssetVersion,
    LegacyReportCutoverStep,
    LegacyReportReconciliation,
    LegacyReportWriteBlock,
)

_CODE = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")
_HASH = re.compile(r"^[0-9a-f]{64}$")


class LegacyReportTakeoverError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class TakeoverOutcome:
    value: object
    created: bool


def _canonical(value) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )


def _digest(value) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _sha256(value, label: str) -> str:
    value = str(value or "").strip().lower()
    if not _HASH.fullmatch(value):
        raise LegacyReportTakeoverError(
            f"HR18_LEGACY_{label}_INVALID", f"{label.lower()} must be sha256"
        )
    return value


def _code(value, label: str) -> str:
    value = str(value or "").strip().upper()
    if not _CODE.fullmatch(value):
        raise LegacyReportTakeoverError(
            f"HR18_LEGACY_{label}_INVALID", f"{label.lower()} is invalid"
        )
    return value


class LegacyReportAssetInventoryService:
    """Inventory one tenant's legacy report templates without mutating them."""

    def __init__(self, tenant_id: int):
        if not tenant_id:
            raise ValueError("tenant_id is required")
        self.tenant_id = int(tenant_id)

    def _legacy_rows(self, limit: int) -> tuple[int, list[dict]]:
        from report.models import ReportTemplate

        qs = (
            ReportTemplate.objects.entire()
            .filter(company_id_id=self.tenant_id)
            .order_by("-created_at", "-id")
        )
        total = qs.count()
        rows = list(
            qs.values(
                "id",
                "report_slug",
                "name",
                "config",
                "created_by_id",
                "created_at",
            )[:limit]
        )
        return total, rows

    def snapshot(self, *, limit: int = 200) -> dict:
        limit = max(1, min(int(limit), 5000))
        total, rows = self._legacy_rows(limit)
        truncated = total > len(rows)
        items = []
        for row in rows:
            source = {
                "id": row["id"],
                "reportSlug": row["report_slug"],
                "name": row["name"],
                "config": row.get("config") or {},
                "createdById": row.get("created_by_id"),
                "createdAt": row.get("created_at"),
            }
            items.append(
                {
                    "legacyReportTemplateId": str(row["id"]),
                    "reportSlug": row["report_slug"],
                    "name": row["name"],
                    "createdById": row.get("created_by_id"),
                    "createdAt": row.get("created_at"),
                    "classification": "NON_AUTHORITY_PREFERENCE_ASSET",
                    "legacyAuthority": False,
                    "canonicalAuthorityMapping": None,
                    "disposition": "MIGRATE_OR_ARCHIVE_USER_PREFERENCE",
                    "config": row.get("config") or {},
                    "sourceEvidenceHash": _digest(source),
                }
            )
        return {
            "status": "PARTIAL" if truncated else "COMPLETE",
            "authority": "HR18",
            "legacySource": "report.ReportTemplate",
            "legacyAuthority": False,
            "mappingPolicy": "NO_FORMAL_AUTHORITY_EQUIVALENT",
            "totalLegacyRows": total,
            "returnedRows": len(items),
            "truncated": truncated,
            "counts": {"nonAuthorityPreferenceAsset": len(items)},
            "items": items,
        }


class LegacyReportTakeoverService:
    SOURCE = "report.ReportTemplate"

    def __init__(self, tenant_id: int, actor_user_id: int | None = None):
        if not tenant_id:
            raise LegacyReportTakeoverError(
                "TENANT_CONTEXT_REQUIRED", "tenant_id is required"
            )
        self.tenant_id = int(tenant_id)
        self.actor_user_id = actor_user_id

    @staticmethod
    def _idempotency(value) -> str:
        value = str(value or "").strip()
        if not value or len(value) > 128:
            raise LegacyReportTakeoverError(
                "HR18_LEGACY_IDEMPOTENCY_KEY_INVALID", "idempotency_key is required"
            )
        return value

    @transaction.atomic
    def inventory(
        self, *, cutover_code, idempotency_key, limit=5000
    ) -> TakeoverOutcome:
        cutover_code = _code(cutover_code, "CUTOVER_CODE")
        idempotency_key = self._idempotency(idempotency_key)
        existing = LegacyReportCutoverStep.objects.filter(
            tenant_id=self.tenant_id, idempotency_key=idempotency_key
        ).first()
        if existing:
            if (
                existing.cutover_code != cutover_code
                or existing.phase != LegacyReportCutoverStep.Phase.INVENTORIED
            ):
                raise LegacyReportTakeoverError(
                    "HR18_LEGACY_IDEMPOTENCY_CONFLICT",
                    "idempotency key has different intent",
                )
            return TakeoverOutcome(existing, False)

        snapshot = LegacyReportAssetInventoryService(self.tenant_id).snapshot(
            limit=limit
        )
        if snapshot["truncated"]:
            raise LegacyReportTakeoverError(
                "HR18_LEGACY_INVENTORY_TRUNCATED",
                "inventory must include every legacy asset",
            )
        now = timezone.now()
        for item in snapshot["items"]:
            legacy_id = int(item["legacyReportTemplateId"])
            config_hash = _digest(item.get("config") or {})
            latest = (
                LegacyReportAssetVersion.objects.select_for_update()
                .filter(
                    tenant_id=self.tenant_id,
                    legacy_source=self.SOURCE,
                    legacy_object_id=legacy_id,
                )
                .order_by("-version_no")
                .first()
            )
            if latest and latest.legacy_config_hash == config_hash:
                continue
            content = {
                "legacySource": self.SOURCE,
                "legacyObjectId": legacy_id,
                "reportSlug": item["reportSlug"],
                "legacyName": item["name"],
                "legacyConfigHash": config_hash,
                "sourceEvidenceHash": item["sourceEvidenceHash"],
                "disposition": "UNAVAILABLE",
            }
            LegacyReportAssetVersion.objects.create(
                tenant_id=self.tenant_id,
                version_no=(latest.version_no + 1 if latest else 1),
                status="INVENTORIED",
                content_hash=_digest(content),
                legacy_source=self.SOURCE,
                legacy_object_id=legacy_id,
                report_slug=item["reportSlug"],
                legacy_name=item["name"],
                legacy_config_hash=config_hash,
                disposition=LegacyReportAssetVersion.Disposition.UNAVAILABLE,
                source_evidence_hash=item["sourceEvidenceHash"],
                inventoried_at=now,
                created_by=self.actor_user_id,
                updated_by=self.actor_user_id,
            )
        assets = self._latest_assets()
        step = self._append_step(
            cutover_code=cutover_code,
            phase=LegacyReportCutoverStep.Phase.INVENTORIED,
            idempotency_key=idempotency_key,
            assets=assets,
            evidence={
                "legacySource": self.SOURCE,
                "inventorySnapshotHash": _digest(snapshot),
                "assetVersionHashes": [asset.content_hash for asset in assets],
            },
        )
        return TakeoverOutcome(step, True)

    @transaction.atomic
    def map_asset(
        self,
        asset_id,
        *,
        disposition,
        canonical_asset_ref="",
        provider_key="",
        mapping=None,
        evidence_hash="",
        idempotency_key="",
    ) -> TakeoverOutcome:
        asset = LegacyReportAssetVersion.objects.select_for_update().filter(
            tenant_id=self.tenant_id, id=asset_id
        ).first()
        if not asset:
            raise LegacyReportTakeoverError(
                "HR18_LEGACY_ASSET_NOT_FOUND",
                "legacy asset does not exist in current tenant",
            )
        idempotency_key = self._idempotency(idempotency_key)
        disposition = str(disposition or "").strip().upper()
        if disposition not in {
            LegacyReportAssetVersion.Disposition.MIGRATE,
            LegacyReportAssetVersion.Disposition.ARCHIVE,
        }:
            raise LegacyReportTakeoverError(
                "HR18_LEGACY_DISPOSITION_INVALID",
                "disposition must be MIGRATE or ARCHIVE",
            )
        mapping = mapping or {}
        if not isinstance(mapping, dict):
            raise LegacyReportTakeoverError(
                "HR18_LEGACY_MAPPING_INVALID", "mapping must be an object"
            )
        canonical_asset_ref = str(canonical_asset_ref or "").strip()
        provider_key = str(provider_key or "").strip().upper()
        if disposition == LegacyReportAssetVersion.Disposition.MIGRATE:
            if not canonical_asset_ref or len(canonical_asset_ref) > 255 or not mapping:
                raise LegacyReportTakeoverError(
                    "HR18_LEGACY_MAPPING_INCOMPLETE",
                    "migrated assets require canonical_asset_ref and mapping",
                )
            if not _CODE.fullmatch(provider_key):
                raise LegacyReportTakeoverError(
                    "HR18_LEGACY_PROVIDER_KEY_INVALID", "provider_key is invalid"
                )
        else:
            mapping = dict(mapping)
            mapping["archiveEvidenceHash"] = _sha256(
                evidence_hash, "ARCHIVE_EVIDENCE_HASH"
            )
            canonical_asset_ref = ""
            provider_key = ""
        content = {
            "priorContentHash": asset.content_hash,
            "disposition": disposition,
            "canonicalAssetRef": canonical_asset_ref,
            "providerKey": provider_key,
            "mapping": mapping,
        }
        content_hash = _digest(content)
        replay = LegacyReportAssetVersion.objects.filter(
            tenant_id=self.tenant_id,
            mapping_idempotency_key=idempotency_key,
        ).first()
        if replay:
            if (
                replay.legacy_object_id != asset.legacy_object_id
                or replay.content_hash != content_hash
            ):
                raise LegacyReportTakeoverError(
                    "HR18_LEGACY_IDEMPOTENCY_CONFLICT",
                    "idempotency key has different mapping intent",
                )
            return TakeoverOutcome(replay, False)
        latest = (
            LegacyReportAssetVersion.objects.filter(
                tenant_id=self.tenant_id,
                legacy_source=asset.legacy_source,
                legacy_object_id=asset.legacy_object_id,
            )
            .order_by("-version_no")
            .first()
        )
        if latest.id != asset.id:
            raise LegacyReportTakeoverError(
                "HR18_LEGACY_ASSET_VERSION_STALE",
                "map the latest inventory version",
            )
        version = LegacyReportAssetVersion.objects.create(
            tenant_id=self.tenant_id,
            version_no=asset.version_no + 1,
            status="MAPPED" if disposition == "MIGRATE" else "ARCHIVE_APPROVED",
            content_hash=content_hash,
            legacy_source=asset.legacy_source,
            legacy_object_id=asset.legacy_object_id,
            report_slug=asset.report_slug,
            legacy_name=asset.legacy_name,
            legacy_config_hash=asset.legacy_config_hash,
            disposition=disposition,
            canonical_asset_ref=canonical_asset_ref,
            provider_key=provider_key,
            mapping_json=mapping,
            mapping_idempotency_key=idempotency_key,
            source_evidence_hash=asset.source_evidence_hash,
            inventoried_at=asset.inventoried_at,
            created_by=self.actor_user_id,
            updated_by=self.actor_user_id,
        )
        return TakeoverOutcome(version, True)

    def _provider(self, provider_key: str):
        configured = getattr(settings, "HR18_LEGACY_REPORT_PROVIDERS", {})
        if not isinstance(configured, dict):
            return None
        path = configured.get(provider_key)
        return import_string(path) if path else None

    @transaction.atomic
    def reconcile(self, asset_id, *, run_no, idempotency_key) -> TakeoverOutcome:
        run_no = _code(run_no, "RECONCILIATION_RUN_NO")
        idempotency_key = self._idempotency(idempotency_key)
        replay = LegacyReportReconciliation.objects.filter(
            tenant_id=self.tenant_id, idempotency_key=idempotency_key
        ).first()
        if replay:
            if str(replay.asset_version_id) != str(asset_id) or replay.run_no != run_no:
                raise LegacyReportTakeoverError(
                    "HR18_LEGACY_IDEMPOTENCY_CONFLICT",
                    "idempotency key has different intent",
                )
            return TakeoverOutcome(replay, False)
        asset = LegacyReportAssetVersion.objects.filter(
            tenant_id=self.tenant_id, id=asset_id
        ).first()
        if not asset:
            raise LegacyReportTakeoverError(
                "HR18_LEGACY_ASSET_NOT_FOUND",
                "legacy asset does not exist in current tenant",
            )
        if asset.disposition != LegacyReportAssetVersion.Disposition.MIGRATE:
            raise LegacyReportTakeoverError(
                "HR18_LEGACY_RECONCILIATION_NOT_REQUIRED",
                "only MIGRATE assets are reconciled",
            )
        provider = self._provider(asset.provider_key)
        payload = None
        unavailable_code = "PROVIDER_NOT_CONFIGURED"
        if provider:
            try:
                payload = provider(
                    tenant_id=self.tenant_id,
                    asset=asset,
                    canonical_asset_ref=asset.canonical_asset_ref,
                    mapping=dict(asset.mapping_json),
                )
            except Exception:
                unavailable_code = "PROVIDER_RUNTIME_FAILURE"
        status = LegacyReportReconciliation.Status.UNAVAILABLE
        provider_version = ""
        legacy_hash = canonical_hash = ""
        legacy_count = canonical_count = None
        evidence = {"availability": unavailable_code}
        differences = {}
        if isinstance(payload, dict):
            provider_version = str(payload.get("providerVersion") or "").strip()
            legacy = payload.get("legacy")
            canonical = payload.get("canonical")
            if (
                payload.get("status") == "COMPLETE"
                and isinstance(legacy, dict)
                and isinstance(canonical, dict)
            ):
                try:
                    legacy_hash = _sha256(
                        legacy.get("outputHash"), "LEGACY_OUTPUT_HASH"
                    )
                    canonical_hash = _sha256(
                        canonical.get("outputHash"), "CANONICAL_OUTPUT_HASH"
                    )
                    legacy_evidence = _sha256(
                        legacy.get("evidenceHash"), "LEGACY_EVIDENCE_HASH"
                    )
                    canonical_evidence = _sha256(
                        canonical.get("evidenceHash"), "CANONICAL_EVIDENCE_HASH"
                    )
                    legacy_count = self._count(legacy.get("recordCount"))
                    canonical_count = self._count(canonical.get("recordCount"))
                    evidence = {
                        "legacyEvidenceHash": legacy_evidence,
                        "canonicalEvidenceHash": canonical_evidence,
                        "providerVersion": provider_version,
                    }
                    if legacy_hash == canonical_hash and legacy_count == canonical_count:
                        status = LegacyReportReconciliation.Status.MATCHED
                    else:
                        status = LegacyReportReconciliation.Status.MISMATCH
                        if legacy_hash != canonical_hash:
                            differences["outputHash"] = {
                                "legacy": legacy_hash,
                                "canonical": canonical_hash,
                            }
                        if legacy_count != canonical_count:
                            differences["recordCount"] = {
                                "legacy": legacy_count,
                                "canonical": canonical_count,
                            }
                except LegacyReportTakeoverError as exc:
                    evidence = {"availability": exc.code}
            else:
                evidence = {
                    "availability": str(
                        payload.get("reasonCode") or "PROVIDER_EVIDENCE_UNAVAILABLE"
                    )[:64]
                }
        evidence_hash = _digest(
            {
                "assetContentHash": asset.content_hash,
                "status": status,
                "legacyOutputHash": legacy_hash,
                "canonicalOutputHash": canonical_hash,
                "legacyRecordCount": legacy_count,
                "canonicalRecordCount": canonical_count,
                "evidence": evidence,
                "differences": differences,
            }
        )
        value = LegacyReportReconciliation.objects.create(
            tenant_id=self.tenant_id,
            run_no=run_no,
            idempotency_key=idempotency_key,
            asset_version=asset,
            status=status,
            provider_version=provider_version,
            legacy_output_hash=legacy_hash,
            canonical_output_hash=canonical_hash,
            legacy_record_count=legacy_count,
            canonical_record_count=canonical_count,
            differences_json=differences,
            evidence_json=evidence,
            evidence_hash=evidence_hash,
            reconciled_at=timezone.now(),
            created_by=self.actor_user_id,
            updated_by=self.actor_user_id,
        )
        return TakeoverOutcome(value, True)

    @staticmethod
    def _count(value):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise LegacyReportTakeoverError(
                "HR18_LEGACY_RECORD_COUNT_INVALID", "record count is invalid"
            )
        return value

    @transaction.atomic
    def advance(self, *, cutover_code, phase, idempotency_key) -> TakeoverOutcome:
        cutover_code = _code(cutover_code, "CUTOVER_CODE")
        phase = str(phase or "").strip().upper()
        allowed = {
            LegacyReportCutoverStep.Phase.DUAL_READ_VERIFIED,
            LegacyReportCutoverStep.Phase.CUTOVER,
            LegacyReportCutoverStep.Phase.LEGACY_WRITE_BLOCKED,
        }
        if phase not in allowed:
            raise LegacyReportTakeoverError(
                "HR18_LEGACY_CUTOVER_PHASE_INVALID", "unsupported cutover phase"
            )
        idempotency_key = self._idempotency(idempotency_key)
        replay = LegacyReportCutoverStep.objects.filter(
            tenant_id=self.tenant_id, idempotency_key=idempotency_key
        ).first()
        if replay:
            if replay.cutover_code != cutover_code or replay.phase != phase:
                raise LegacyReportTakeoverError(
                    "HR18_LEGACY_IDEMPOTENCY_CONFLICT",
                    "idempotency key has different intent",
                )
            return TakeoverOutcome(replay, False)
        latest_step = (
            LegacyReportCutoverStep.objects.select_for_update()
            .filter(tenant_id=self.tenant_id, cutover_code=cutover_code)
            .order_by("-step_no")
            .first()
        )
        if not latest_step:
            raise LegacyReportTakeoverError(
                "HR18_LEGACY_INVENTORY_REQUIRED", "inventory step is required"
            )
        required = {
            LegacyReportCutoverStep.Phase.DUAL_READ_VERIFIED: LegacyReportCutoverStep.Phase.INVENTORIED,
            LegacyReportCutoverStep.Phase.CUTOVER: LegacyReportCutoverStep.Phase.DUAL_READ_VERIFIED,
            LegacyReportCutoverStep.Phase.LEGACY_WRITE_BLOCKED: LegacyReportCutoverStep.Phase.CUTOVER,
        }[phase]
        retrying_unavailable_dual_read = (
            phase == LegacyReportCutoverStep.Phase.DUAL_READ_VERIFIED
            and latest_step.phase == LegacyReportCutoverStep.Phase.UNAVAILABLE
        )
        if latest_step.phase != required and not retrying_unavailable_dual_read:
            raise LegacyReportTakeoverError(
                "HR18_LEGACY_CUTOVER_SEQUENCE_INVALID", f"{required} step is required"
            )
        assets = self._latest_assets()
        matched = archived = unavailable = 0
        evidence_assets = []
        for asset in assets:
            if asset.disposition == LegacyReportAssetVersion.Disposition.ARCHIVE:
                archive_hash = str(
                    asset.mapping_json.get("archiveEvidenceHash") or ""
                )
                if _HASH.fullmatch(archive_hash):
                    archived += 1
                    evidence_assets.append(
                        {"asset": str(asset.id), "archiveEvidenceHash": archive_hash}
                    )
                else:
                    unavailable += 1
            elif asset.disposition == LegacyReportAssetVersion.Disposition.MIGRATE:
                reconciliation = asset.reconciliations.order_by(
                    "-reconciled_at"
                ).first()
                if (
                    reconciliation
                    and reconciliation.status
                    == LegacyReportReconciliation.Status.MATCHED
                ):
                    matched += 1
                    evidence_assets.append(
                        {
                            "asset": str(asset.id),
                            "reconciliationHash": reconciliation.evidence_hash,
                        }
                    )
                else:
                    unavailable += 1
            else:
                unavailable += 1
        if phase == LegacyReportCutoverStep.Phase.DUAL_READ_VERIFIED and unavailable:
            step = self._append_step(
                cutover_code=cutover_code,
                phase=LegacyReportCutoverStep.Phase.UNAVAILABLE,
                idempotency_key=idempotency_key,
                assets=assets,
                evidence={"requiredPhase": phase, "assetEvidence": evidence_assets},
                matched=matched,
                archived=archived,
                unavailable=unavailable,
            )
            return TakeoverOutcome(step, True)
        if unavailable:
            raise LegacyReportTakeoverError(
                "HR18_LEGACY_CUTOVER_EVIDENCE_UNAVAILABLE",
                "all assets require matched or archive evidence",
            )
        step = self._append_step(
            cutover_code=cutover_code,
            phase=phase,
            idempotency_key=idempotency_key,
            assets=assets,
            evidence={
                "priorStepHash": latest_step.evidence_hash,
                "assetEvidence": evidence_assets,
                "legacySource": self.SOURCE,
            },
            matched=matched,
            archived=archived,
            unavailable=0,
        )
        if phase == LegacyReportCutoverStep.Phase.LEGACY_WRITE_BLOCKED:
            LegacyReportWriteBlock.objects.get_or_create(
                tenant_id=self.tenant_id,
                legacy_source=self.SOURCE,
                defaults={
                    "cutover_step": step,
                    "evidence_hash": _digest(
                        {
                            "cutoverStepHash": step.evidence_hash,
                            "legacySource": self.SOURCE,
                        }
                    ),
                    "activated_at": timezone.now(),
                    "created_by": self.actor_user_id,
                    "updated_by": self.actor_user_id,
                },
            )
        return TakeoverOutcome(step, True)

    def _latest_assets(self):
        rows = list(
            LegacyReportAssetVersion.objects.filter(
                tenant_id=self.tenant_id, legacy_source=self.SOURCE
            ).order_by("legacy_object_id", "-version_no")
        )
        latest = {}
        for row in rows:
            latest.setdefault(row.legacy_object_id, row)
        return list(latest.values())

    def _append_step(
        self,
        *,
        cutover_code,
        phase,
        idempotency_key,
        assets,
        evidence,
        matched=0,
        archived=0,
        unavailable=None,
    ):
        previous = (
            LegacyReportCutoverStep.objects.select_for_update()
            .filter(tenant_id=self.tenant_id, cutover_code=cutover_code)
            .order_by("-step_no")
            .first()
        )
        if unavailable is None:
            unavailable = sum(
                asset.disposition == LegacyReportAssetVersion.Disposition.UNAVAILABLE
                for asset in assets
            )
        body = {
            "cutoverCode": cutover_code,
            "stepNo": previous.step_no + 1 if previous else 1,
            "phase": phase,
            "assetCount": len(assets),
            "matchedCount": matched,
            "archivedCount": archived,
            "unavailableCount": unavailable,
            "evidence": evidence,
        }
        return LegacyReportCutoverStep.objects.create(
            tenant_id=self.tenant_id,
            cutover_code=cutover_code,
            step_no=body["stepNo"],
            phase=phase,
            idempotency_key=idempotency_key,
            asset_count=len(assets),
            matched_count=matched,
            archived_count=archived,
            unavailable_count=unavailable,
            evidence_json=evidence,
            evidence_hash=_digest(body),
            recorded_at=timezone.now(),
            created_by=self.actor_user_id,
            updated_by=self.actor_user_id,
        )


def legacy_report_write_block(tenant_id: int):
    """Return the immutable block receipt for a tenant, or ``None``."""

    if not tenant_id:
        return None
    return (
        LegacyReportWriteBlock.objects.filter(
            tenant_id=int(tenant_id),
            legacy_source=LegacyReportTakeoverService.SOURCE,
        )
        .select_related("cutover_step")
        .first()
    )
