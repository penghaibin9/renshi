"""
hr_changes/management/commands/hr06_switch_authority.py

Authority 切换（S12，00 §56 合法顺序推进）。
用法：python manage.py hr06_switch_authority --tenant=1 --mode=DUAL_READ_COMPARE
"""

from django.core.management.base import BaseCommand, CommandError

from hr_changes.services.authority_mode_service import (
    AuthorityModeError,
    AuthorityModeService,
)


class Command(BaseCommand):
    help = "Switch HR06 authority mode (sequential: LEGACY_ACTIVE → DUAL_READ_COMPARE → HR06_AUTHORITY → LEGACY_READONLY_PROJECTION)"

    def add_arguments(self, parser):
        parser.add_argument("--tenant", type=int, required=True, help="tenant_id")
        parser.add_argument("--mode", required=True, help="目标模式")
        parser.add_argument("--note", default="", help="切换说明")

    def handle(self, *args, **options):
        try:
            row = AuthorityModeService(options["tenant"]).switch(
                options["mode"], note=options["note"]
            )
        except AuthorityModeError as exc:
            raise CommandError(f"{exc.code}: {exc.message}")
        self.stdout.write(
            self.style.SUCCESS(f"tenant={options['tenant']} mode={row.mode}")
        )
