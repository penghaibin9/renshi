"""Tenant-scoped, ordered and durable HR12 Authority cutover orchestration."""

from __future__ import annotations

import hashlib
import json

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.db.migrations.executor import MigrationExecutor

from hr_assessment.legacy.write_seal import (
    is_pms_write_frozen,
    set_pms_write_frozen,
)
from hr_assessment.models import HrAssessmentCutoverEvent
from hr_control_center.models import HrAuthorityCutover


PHASES = [
    "LEGACY_ACTIVE",
    "NEW_STAGING",
    "DUAL_READ_COMPARE",
    "SHADOW_EXECUTION",
    "FREEZE_LEGACY_FORMAL_WRITES",
    "NEW_AUTHORITY",
    "LEGACY_READONLY_PROJECTION",
    "POST_CUTOVER_CLEANUP",
]

PHASE_MODE = {
    "LEGACY_ACTIVE": HrAuthorityCutover.Mode.LEGACY_ONLY,
    "NEW_STAGING": HrAuthorityCutover.Mode.LEGACY_ONLY,
    "DUAL_READ_COMPARE": HrAuthorityCutover.Mode.DUAL_READ_COMPARE,
    "SHADOW_EXECUTION": HrAuthorityCutover.Mode.DUAL_READ_COMPARE,
    "FREEZE_LEGACY_FORMAL_WRITES": HrAuthorityCutover.Mode.DUAL_READ_COMPARE,
    "NEW_AUTHORITY": HrAuthorityCutover.Mode.AUTHORITY_ONLY,
    "LEGACY_READONLY_PROJECTION": HrAuthorityCutover.Mode.AUTHORITY_ONLY,
    "POST_CUTOVER_CLEANUP": HrAuthorityCutover.Mode.AUTHORITY_ONLY,
}


class Command(BaseCommand):
    help = "HR12 Authority 按学校、按阶段切换（持久状态 + 追加审计）"

    def add_arguments(self, parser):
        parser.add_argument("--phase", required=True, choices=PHASES)
        parser.add_argument("--tenant-id", type=int, required=True)
        parser.add_argument("--operator", default="SYSTEM")
        parser.add_argument("--reason", default="HR12 Authority cutover")
        parser.add_argument("--verification-report-id", default="")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, **options):
        phase = options["phase"]
        tenant_id = int(options["tenant_id"])
        operator = str(options.get("operator") or "").strip() or "SYSTEM"
        reason = str(options.get("reason") or "").strip()
        verification_report_id = str(
            options.get("verification_report_id") or ""
        ).strip()
        dry_run = bool(options.get("dry_run"))

        if tenant_id <= 0:
            raise CommandError("--tenant-id 必须是正整数")
        if not reason:
            raise CommandError("--reason 不能为空")
        if len(reason) > 255:
            raise CommandError("--reason 不能超过 255 字符")

        current = (
            HrAssessmentCutoverEvent.objects.filter(tenant_id=tenant_id)
            .order_by("-occurred_at", "-id")
            .first()
        )
        current_phase = current.phase if current is not None else ""
        self._assert_order(current_phase=current_phase, target_phase=phase)

        if current_phase == phase:
            self.stdout.write(
                self.style.SUCCESS(
                    f"tenant={tenant_id} phase={phase} 已完成，本次为幂等重放"
                )
            )
            return

        if dry_run:
            details = self._run_gate(
                phase=phase,
                tenant_id=tenant_id,
                operator=operator,
                reason=reason,
                verification_report_id=verification_report_id,
                dry_run=True,
            )
            self.stdout.write(
                self.style.WARNING(
                    f"[DRY RUN] tenant={tenant_id} {current_phase or 'NONE'} → {phase}; "
                    f"checks={details}"
                )
            )
            return

        target_mode = PHASE_MODE[phase]
        with transaction.atomic():
            # Freeze + current-state update + append-only event commit together.
            # Any persistence failure rolls the writer seal back as well.
            details = self._run_gate(
                phase=phase,
                tenant_id=tenant_id,
                operator=operator,
                reason=reason,
                verification_report_id=verification_report_id,
                dry_run=False,
            )
            snapshot_hash = hashlib.sha256(
                json.dumps(details, sort_keys=True, default=str).encode("utf-8")
            ).hexdigest()
            cutover, _ = HrAuthorityCutover.objects.select_for_update().get_or_create(
                tenant_id=tenant_id,
                domain=HrAuthorityCutover.Domain.ASSESSMENT,
                defaults={
                    "mode": target_mode,
                    "cutover_by": operator,
                    "reason": reason,
                    "source_snapshot_hash": snapshot_hash,
                    "mapping_version": "HR12_CUTOVER_V1",
                    "verification_report_id": verification_report_id,
                },
            )
            cutover.mode = target_mode
            cutover.cutover_by = operator
            cutover.reason = reason
            cutover.source_snapshot_hash = snapshot_hash
            cutover.mapping_version = "HR12_CUTOVER_V1"
            cutover.verification_report_id = verification_report_id
            cutover.save(
                update_fields=(
                    "mode",
                    "cutover_by",
                    "reason",
                    "source_snapshot_hash",
                    "mapping_version",
                    "verification_report_id",
                    "cutover_at",
                )
            )
            HrAssessmentCutoverEvent.objects.create(
                tenant_id=tenant_id,
                phase=phase,
                previous_phase=current_phase,
                authority_mode=target_mode,
                operator=operator,
                reason=reason,
                verification_report_id=verification_report_id,
                source_snapshot_hash=snapshot_hash,
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"tenant={tenant_id} {current_phase or 'NONE'} → {phase}; mode={target_mode}"
            )
        )

    @staticmethod
    def _assert_order(*, current_phase: str, target_phase: str) -> None:
        target_index = PHASES.index(target_phase)
        if not current_phase:
            if target_index != 0:
                raise CommandError("首次切权必须从 LEGACY_ACTIVE 开始")
            return
        current_index = PHASES.index(current_phase)
        if target_index not in (current_index, current_index + 1):
            raise CommandError(
                f"非法阶段跳转: {current_phase} → {target_phase}; "
                f"下一阶段必须是 {PHASES[min(current_index + 1, len(PHASES) - 1)]}"
            )

    def _run_gate(
        self,
        *,
        phase: str,
        tenant_id: int,
        operator: str,
        reason: str,
        verification_report_id: str,
        dry_run: bool,
    ) -> dict:
        if phase == "LEGACY_ACTIVE":
            from pms.models import Period

            count = Period.objects.filter(company_id__id=tenant_id).distinct().count()
            return {"legacyPeriodCount": count}

        if phase == "NEW_STAGING":
            executor = MigrationExecutor(connection)
            targets = executor.loader.graph.leaf_nodes("hr_assessment")
            pending = executor.migration_plan(targets)
            if pending:
                names = [f"{migration.app_label}.{migration.name}" for migration, _ in pending]
                raise CommandError("HR12 尚有未应用迁移: " + ", ".join(names[:20]))
            return {"assessmentMigrationsApplied": True}

        if phase == "DUAL_READ_COMPARE":
            try:
                call_command("dual_read_compare", tenant_id=tenant_id, verbosity=0)
            except SystemExit as exc:
                raise CommandError("HR12 双读对账存在阻断差异") from exc
            return {
                "dualReadCompared": True,
                "verificationReportId": verification_report_id,
            }

        if phase == "SHADOW_EXECUTION":
            if is_pms_write_frozen():
                raise CommandError("进入影子执行前 legacy PMS 不应已被冻结")
            return {"shadowExecution": True, "formalWriter": "LEGACY_PMS"}

        if phase == "FREEZE_LEGACY_FORMAL_WRITES":
            if not dry_run:
                seal = set_pms_write_frozen(
                    frozen=True,
                    reason=reason,
                    operator=operator,
                )
                return {"legacyWriterFrozen": True, "sealRevision": seal.revision}
            return {"legacyWriterWouldFreeze": True}

        if phase == "NEW_AUTHORITY":
            if not is_pms_write_frozen():
                raise CommandError("legacy PMS 正式写入口尚未冻结，禁止切到 HR12 Authority")
            if not verification_report_id:
                raise CommandError("切到 NEW_AUTHORITY 必须提供 --verification-report-id")
            return {
                "legacyWriterFrozen": True,
                "verificationReportId": verification_report_id,
            }

        if phase == "LEGACY_READONLY_PROJECTION":
            if not is_pms_write_frozen():
                raise CommandError("legacy PMS 写入口未冻结，不能声明只读投影")
            return {"legacyProjection": "READ_ONLY"}

        if phase == "POST_CUTOVER_CLEANUP":
            if not is_pms_write_frozen():
                raise CommandError("legacy PMS 写入口未冻结，不能完成切后清理")
            return {"cleanupVerified": True, "destructiveCleanupPerformed": False}

        raise CommandError(f"未知 HR12 切权阶段: {phase}")
