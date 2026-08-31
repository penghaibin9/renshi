"""Manage the durable HR12 seal for legacy PMS formal writes."""

from django.core.management.base import BaseCommand

from hr_assessment.legacy.write_seal import (
    is_pms_write_frozen,
    set_pms_write_frozen,
)
from hr_assessment.models.legacy import HrLegacyPmsWriterSealEvent


class Command(BaseCommand):
    help = "冻结/解冻旧 PMS 写操作"

    def add_arguments(self, parser):
        parser.add_argument("action", choices=["freeze", "unfreeze", "status"])
        parser.add_argument("--reason", default="")
        parser.add_argument("--operator", default="SYSTEM")

    def handle(self, **options):
        action = options["action"]

        if action == "freeze":
            self._do_freeze(options["reason"], options["operator"])
        elif action == "unfreeze":
            self._do_unfreeze(options["reason"], options["operator"])
        elif action == "status":
            self._show_status()

    def _do_freeze(self, reason: str, operator: str):
        seal = set_pms_write_frozen(frozen=True, reason=reason, operator=operator)
        self.stdout.write(self.style.SUCCESS(
            f"Legacy PMS formal writer FROZEN revision={seal.revision} "
            f"operator={seal.operator} reason={seal.reason}"
        ))

    def _do_unfreeze(self, reason: str, operator: str):
        seal = set_pms_write_frozen(frozen=False, reason=reason, operator=operator)
        self.stdout.write(self.style.WARNING(
            f"Legacy PMS formal writer UNFROZEN revision={seal.revision} "
            f"operator={seal.operator}"
        ))

    def _show_status(self):
        frozen = is_pms_write_frozen()
        latest = HrLegacyPmsWriterSealEvent.objects.order_by("-occurred_at").first()
        if frozen:
            self.stdout.write("Status: FROZEN — 旧 PMS 写操作已冻结")
        else:
            self.stdout.write("Status: ACTIVE — 旧 PMS 写操作仍可用")
        if latest:
            self.stdout.write(
                f"最近操作: action={latest.action} revision={latest.revision} "
                f"operator={latest.operator} reason={latest.reason}"
            )


__all__ = ["Command", "is_pms_write_frozen"]
