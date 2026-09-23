"""Read-only tenant go-live audit for the University HR suite.

This command intentionally does not provision data, flip authority modes, or
repair queues.  It aggregates the existing production gates so an operator can
get one machine-readable launch verdict before opening traffic.
"""

from __future__ import annotations

import io
import json
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from django.utils import timezone

from horilla.settings.security import (
    validate_field_encryption_configuration,
    validate_field_fingerprint_configuration,
    validate_hr08_ticket_signing_configuration,
)
from hr_control_center.services.authority_gate_service import AuthorityGateService


class Command(BaseCommand):
    help = "Run one read-only production launch audit for a tenant (security, authority, queues, imports)."

    def add_arguments(self, parser):
        parser.add_argument("--tenant", type=int, required=True)
        parser.add_argument(
            "--strict",
            action="store_true",
            help="Treat WARN checks as blockers in addition to BLOCKER checks.",
        )
        parser.add_argument(
            "--json-out",
            default="",
            help="Optional path for the JSON evidence file; stdout always contains the verdict.",
        )

    @staticmethod
    def _row(code: str, severity: str, ok: bool, detail: str, **evidence):
        return {
            "code": code,
            "severity": severity,
            "ok": bool(ok),
            "detail": detail,
            "evidence": evidence,
        }

    def handle(self, *args, **options):
        tenant_id = int(options["tenant"])
        if tenant_id <= 0:
            raise CommandError("--tenant 必须是正整数")
        strict = bool(options.get("strict"))
        rows = []

        rows.append(self._check_separated_keys())
        rows.append(self._check_field_rewrap(tenant_id))
        rows.append(self._check_authority_gate(tenant_id))
        rows.extend(self._check_hr05_import_ledger(tenant_id))
        rows.extend(self._check_outboxes(tenant_id))
        rows.extend(self._check_external_runtime_queues(tenant_id))
        rows.extend(self._check_worker_heartbeats())
        rows.append(self._check_hr09_cutover(tenant_id))

        blockers = [row for row in rows if not row["ok"] and row["severity"] == "BLOCKER"]
        warnings = [row for row in rows if not row["ok"] and row["severity"] == "WARN"]
        ready = not blockers and (not strict or not warnings)
        payload = {
            "schema": "yueke.hr.go-live-audit.1",
            "generatedAt": timezone.now().isoformat(),
            "tenantId": tenant_id,
            "strict": strict,
            "status": "READY_FOR_RUNTIME_ACCEPTANCE" if ready else "BLOCKED",
            "summary": {
                "checks": len(rows),
                "blockers": len(blockers),
                "warnings": len(warnings),
            },
            "checks": rows,
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2)
        self.stdout.write(encoded)
        output_path = str(options.get("json_out") or "").strip()
        if output_path:
            from pathlib import Path

            target = Path(output_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(encoded + "\n", encoding="utf-8")
        if not ready:
            raise CommandError(
                f"HR_GO_LIVE_BLOCKED blockers={len(blockers)} warnings={len(warnings)} strict={strict}"
            )

    def _check_separated_keys(self):
        encryption_keys = str(getattr(settings, "FIELD_ENCRYPTION_KEYS", "") or "")
        fingerprint_key = str(getattr(settings, "FIELD_FINGERPRINT_KEY", "") or "")
        ticket_key = str(getattr(settings, "HR08_TICKET_SIGNING_KEY", "") or "")
        secret_key = str(getattr(settings, "SECRET_KEY", "") or "")
        backup_key = str(getattr(settings, "PRODUCTION_BACKUP_ENCRYPTION_KEY", "") or "")
        try:
            validate_field_encryption_configuration(
                encryption_keys,
                production=True,
                disallowed_secrets=(secret_key, backup_key, fingerprint_key, ticket_key),
            )
            validate_field_fingerprint_configuration(
                fingerprint_key,
                secret_key=secret_key,
                backup_key=backup_key,
                encryption_keys=encryption_keys,
                production=True,
            )
            validate_hr08_ticket_signing_configuration(
                ticket_key,
                secret_key=secret_key,
                fingerprint_key=fingerprint_key,
                backup_key=backup_key,
                encryption_keys=encryption_keys,
                production=True,
            )
        except ImproperlyConfigured as exc:
            return self._row("SEPARATED_HR_SECRETS", "BLOCKER", False, str(exc))
        return self._row(
            "SEPARATED_HR_SECRETS",
            "BLOCKER",
            True,
            "field encryption, searchable fingerprints and HR08 tickets use distinct production secrets",
        )

    def _check_field_rewrap(self, tenant_id: int):
        stdout = io.StringIO()
        try:
            call_command("rotate_hr_field_security", check=True, tenant=tenant_id, stdout=stdout, stderr=stdout)
        except CommandError as exc:
            detail = (stdout.getvalue().strip() + " | " + str(exc)).strip(" |")
            return self._row("HR_FIELD_SECURITY_REWRAP", "BLOCKER", False, detail[:2000])
        return self._row(
            "HR_FIELD_SECURITY_REWRAP",
            "BLOCKER",
            True,
            stdout.getvalue().strip()[:2000] or "all supported sensitive HR fields use current keys",
        )

    def _check_authority_gate(self, tenant_id: int):
        try:
            payload = AuthorityGateService(tenant_id=tenant_id, limit=200).run(
                require_reconciliation=True,
                require_zero_legacy_writes=True,
            )
        except Exception as exc:  # noqa: BLE001 - audit must normalize runtime gate failures
            return self._row("HR01_HR18_AUTHORITY_GATE", "BLOCKER", False, str(exc)[:2000])
        ok = payload.get("status") == "COMPLETE"
        return self._row(
            "HR01_HR18_AUTHORITY_GATE",
            "BLOCKER",
            ok,
            f"authority gate status={payload.get('status')}",
            errorCount=len(payload.get("errors") or []),
            warningCount=len(payload.get("warnings") or []),
        )

    def _check_hr05_import_ledger(self, tenant_id: int):
        from hr_onboarding.models import HrOnboardingImportJob

        cutoff = timezone.now() - timedelta(minutes=15)
        stale = (
            HrOnboardingImportJob.objects.filter(
                tenant_id=tenant_id,
                status=HrOnboardingImportJob.Status.COMMITTING,
            )
            .filter(
                Q(commit_started_at__lt=cutoff)
                | Q(commit_started_at__isnull=True, updated_at__lt=cutoff)
            )
            .count()
        )
        failed = HrOnboardingImportJob.objects.filter(
            tenant_id=tenant_id,
            status=HrOnboardingImportJob.Status.FAILED,
        ).count()
        return [
            self._row(
                "HR05_IMPORT_STALE_COMMIT",
                "BLOCKER",
                stale == 0,
                f"stale COMMITTING jobs={stale}",
                stale=stale,
            ),
            self._row(
                "HR05_IMPORT_FAILED_HISTORY",
                "WARN",
                failed == 0,
                f"historical failed import jobs={failed}; review error ledgers before launch",
                failed=failed,
            ),
        ]

    def _check_outboxes(self, tenant_id: int):
        from hr_changes.models import HrChangeOutboxEvent
        from hr_onboarding.models import HrOnboardingOutboxEvent
        from hr_staff.models import HrOutboxEvent

        rows = []
        dead = HrOutboxEvent.objects.filter(
            tenant_id=tenant_id, status=HrOutboxEvent.Status.DEAD
        ).count()
        rows.append(self._row("HR03_OUTBOX_DEAD", "BLOCKER", dead == 0, f"dead events={dead}", count=dead))
        dropped05 = HrOnboardingOutboxEvent.objects.filter(
            tenant_id=tenant_id, status=HrOnboardingOutboxEvent.Status.DROPPED
        ).count()
        rows.append(
            self._row("HR05_OUTBOX_DROPPED", "BLOCKER", dropped05 == 0, f"dropped events={dropped05}", count=dropped05)
        )
        cutoff = timezone.now() - timedelta(minutes=15)
        stale05 = HrOnboardingOutboxEvent.objects.filter(
            tenant_id=tenant_id,
            status=HrOnboardingOutboxEvent.Status.PENDING,
            occurred_at__lt=cutoff,
        ).count()
        rows.append(
            self._row(
                "HR05_OUTBOX_STALE_PENDING",
                "BLOCKER",
                stale05 == 0,
                f"PENDING events older than 15m={stale05}",
                count=stale05,
            )
        )
        failed05 = HrOnboardingOutboxEvent.objects.filter(
            tenant_id=tenant_id, status=HrOnboardingOutboxEvent.Status.FAILED
        ).count()
        rows.append(
            self._row(
                "HR05_OUTBOX_FAILED",
                "BLOCKER",
                failed05 == 0,
                f"terminal/verification failed events={failed05}",
                count=failed05,
            )
        )
        dropped06 = HrChangeOutboxEvent.objects.filter(
            tenant_id=tenant_id, status=HrChangeOutboxEvent.Status.DROPPED
        ).count()
        rows.append(
            self._row("HR06_OUTBOX_DROPPED", "BLOCKER", dropped06 == 0, f"dropped events={dropped06}", count=dropped06)
        )
        failed = (
            HrOutboxEvent.objects.filter(tenant_id=tenant_id, status=HrOutboxEvent.Status.FAILED).count()
            + HrChangeOutboxEvent.objects.filter(tenant_id=tenant_id, status=HrChangeOutboxEvent.Status.FAILED).count()
        )
        rows.append(
            self._row("HR_CORE_OUTBOX_FAILED", "WARN", failed == 0, f"retryable failed events={failed}", count=failed)
        )
        return rows

    def _check_external_runtime_queues(self, tenant_id: int):
        """Fail closed on terminal integration queues that would strand launch data."""
        from hr_data.models import ExchangeJob, SubmissionDispatchJob
        from hr_external.constants import ProvisioningStatus
        from hr_external.models import (
            HrExternalAcademicProvisioningRequest,
            HrExternalProvisioningRequest,
        )

        submission_dead = SubmissionDispatchJob.objects.filter(
            tenant_id=tenant_id, status=SubmissionDispatchJob.Status.DEAD
        ).count()
        exchange_dead = ExchangeJob.objects.filter(
            tenant_id=tenant_id, status=ExchangeJob.Status.DEAD_LETTER
        ).count()
        hr08_failed = (
            HrExternalProvisioningRequest.objects.filter(
                tenant_id=tenant_id, status=ProvisioningStatus.FAILED
            ).count()
            + HrExternalAcademicProvisioningRequest.objects.filter(
                tenant_id=tenant_id, status=ProvisioningStatus.FAILED
            ).count()
        )
        hr08_retryable = (
            HrExternalProvisioningRequest.objects.filter(
                tenant_id=tenant_id, status=ProvisioningStatus.FAILED_RETRYABLE
            ).count()
            + HrExternalAcademicProvisioningRequest.objects.filter(
                tenant_id=tenant_id, status=ProvisioningStatus.FAILED_RETRYABLE
            ).count()
        )
        return [
            self._row(
                "HR18_SUBMISSION_DEAD", "BLOCKER", submission_dead == 0,
                f"dead formal-submission jobs={submission_dead}", count=submission_dead,
            ),
            self._row(
                "HR18_EXCHANGE_DEAD_LETTER", "BLOCKER", exchange_dead == 0,
                f"dead-letter exchange jobs={exchange_dead}", count=exchange_dead,
            ),
            self._row(
                "HR08_PROVISIONING_FAILED", "BLOCKER", hr08_failed == 0,
                f"terminal IAM/academic provisioning failures={hr08_failed}", count=hr08_failed,
            ),
            self._row(
                "HR08_PROVISIONING_RETRYABLE", "WARN", hr08_retryable == 0,
                f"retryable IAM/academic provisioning failures={hr08_retryable}", count=hr08_retryable,
            ),
        ]

    def _check_worker_heartbeats(self):
        """Prove the production background owners are alive before traffic opens."""
        try:
            import time
            import redis

            redis_url = str(getattr(settings, "REDIS_URL", "") or "").strip()
            if not redis_url:
                raise RuntimeError("REDIS_URL is empty")
            client = redis.Redis.from_url(
                redis_url, socket_connect_timeout=3, socket_timeout=3
            )
            now = time.time()
            expected = {
                "hr05-outbox": 120,
                "hr05-import": 120,
                "hr18-submission": 120,
                "hr18-exchange": 120,
                "legacy-scheduler": 120,
                "employee-scheduler": 120,
                "backup-scheduler": 180,
            }
            rows = []
            for name, max_age in expected.items():
                raw = client.get(f"renshi:worker:{name}:heartbeat")
                if raw is None:
                    rows.append(self._row(
                        f"WORKER_{name.upper().replace('-', '_')}",
                        "BLOCKER", False, f"heartbeat missing for {name}", worker=name,
                    ))
                    continue
                age = now - float(raw)
                ok = 0 <= age <= max_age
                rows.append(self._row(
                    f"WORKER_{name.upper().replace('-', '_')}",
                    "BLOCKER", ok, f"heartbeat age={age:.1f}s max={max_age}s",
                    worker=name, ageSeconds=round(age, 3), maxAgeSeconds=max_age,
                ))
            return rows
        except Exception as exc:  # noqa: BLE001 - missing runtime ownership is a blocker
            return [self._row(
                "PRODUCTION_WORKER_HEARTBEATS",
                "BLOCKER",
                False,
                f"worker heartbeat audit unavailable: {exc}"[:2000],
            )]

    def _check_hr09_cutover(self, tenant_id: int):
        from hr_qualification.models import HrDoubleTeacherRecognition, HrPersonCredential
        from hr_qualification.services.authority_mode_service import (
            QualificationAuthorityMode,
            QualificationAuthorityModeService,
        )

        try:
            authority_rows = HrPersonCredential.objects.filter(tenant_id=tenant_id).count()
            authority_rows += HrDoubleTeacherRecognition.objects.filter(tenant_id=tenant_id).count()
            mode = QualificationAuthorityModeService().get_mode(tenant_id)
        except Exception as exc:  # noqa: BLE001 - audit must fail closed on cutover/read errors
            return self._row(
                "HR09_AUTHORITY_CUTOVER",
                "BLOCKER",
                False,
                f"HR09 cutover state unavailable: {exc}"[:2000],
            )
        ok = authority_rows == 0 or mode == QualificationAuthorityMode.HR09_AUTHORITY
        severity = "BLOCKER" if authority_rows else "WARN"
        detail = f"mode={mode}; qualification authority rows={authority_rows}"
        return self._row("HR09_AUTHORITY_CUTOVER", severity, ok, detail, mode=mode, rows=authority_rows)
