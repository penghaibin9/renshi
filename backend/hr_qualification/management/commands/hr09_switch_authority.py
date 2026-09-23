"""Persisted HR09 authority cutover command."""

from django.core.management.base import BaseCommand, CommandError

from hr_qualification.services.authority_mode_service import (
    QualificationAuthorityMode,
    QualificationAuthorityModeError,
    QualificationAuthorityModeService,
)


_MODE_CHOICES = [
    QualificationAuthorityMode.LEGACY,
    QualificationAuthorityMode.DUAL_READ_COMPARE,
    QualificationAuthorityMode.HR09_AUTHORITY,
]


class Command(BaseCommand):
    help = "Persist HR09 authority mode in the shared tenant cutover ledger."

    def add_arguments(self, parser):
        parser.add_argument("--tenant-id", type=int, required=True)
        parser.add_argument("--mode", choices=_MODE_CHOICES, required=True)
        parser.add_argument("--reason", required=True)
        parser.add_argument("--cutover-by", default="")
        parser.add_argument("--verification-report-id", default="")
        parser.add_argument("--force", action="store_true", default=False)

    def handle(self, *args, **options):
        tenant_id = options["tenant_id"]
        mode = options["mode"]
        reason = options["reason"]
        report_id = options["verification_report_id"]

        if mode == QualificationAuthorityMode.HR09_AUTHORITY and not report_id:
            raise CommandError(
                "HR09_AUTHORITY requires --verification-report-id from the dual-read reconciliation evidence"
            )

        if not options["force"]:
            self.stdout.write(
                self.style.WARNING(
                    f"tenant {tenant_id} HR09 authority -> {mode}\n"
                    "Before switching confirm legacy migration, dual-read reconciliation, "
                    "and legacy write-path closure."
                )
            )
            if input("Type YES to confirm: ") != "YES":
                self.stdout.write("Cancelled.")
                return

        if mode == QualificationAuthorityMode.DUAL_READ_COMPARE:
            from hr_qualification.services.legacy_projection import (
                LegacyQualificationProjection,
            )

            result = LegacyQualificationProjection.bulk_rebuild(tenant_id)
            if result.get("error") or int(result.get("failed", 0)):
                raise CommandError(
                    "HR09 legacy projection rebuild failed; authority mode was not changed: "
                    f"{result}"
                )
            self.stdout.write(f"Legacy projection rebuild: {result}")

        service = QualificationAuthorityModeService()
        try:
            row = service.record_cutover(
                tenant_id=tenant_id,
                mode=mode,
                reason=reason,
                cutover_by=options["cutover_by"],
                verification_report_id=report_id,
            )
        except QualificationAuthorityModeError as exc:
            raise CommandError(str(exc)) from exc

        persisted = service.get_mode(tenant_id)
        if persisted != mode:
            raise CommandError(
                f"HR09 authority persistence mismatch: requested={mode}, persisted={persisted}"
            )
        self.stdout.write(
            self.style.SUCCESS(
                f"HR09_AUTHORITY_CUTOVER_OK tenant={tenant_id} mode={persisted} cutover_id={row.pk}"
            )
        )
