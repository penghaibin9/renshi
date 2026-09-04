"""Run deployment preparation in one Django process."""

from django.conf import settings
from django.core import checks
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Run optional migrate/collectstatic and mandatory system checks once."

    def add_arguments(self, parser):
        parser.add_argument("--migrate", action="store_true")
        parser.add_argument("--collectstatic", action="store_true")

    def handle(self, *args, **options):
        if options["migrate"]:
            call_command("migrate", interactive=False)
        if options["collectstatic"]:
            call_command("collectstatic", interactive=False, verbosity=0)
        is_production = bool(getattr(settings, "IS_PRODUCTION", False))
        messages = checks.run_checks(include_deployment_checks=is_production)
        silenced_ids = set(getattr(settings, "SILENCED_SYSTEM_CHECKS", ()))
        visible = [message for message in messages if message.id not in silenced_ids]

        # Development keeps Django's normal ERROR threshold. A production
        # release, however, must fail on every previously unknown warning. Any
        # accepted framework warning has to be reviewed and explicitly listed
        # in SILENCED_SYSTEM_CHECKS, so the release log remains auditable.
        failure_level = checks.WARNING if is_production else checks.ERROR
        blocking = [
            message for message in visible if message.is_serious(failure_level)
        ]
        if blocking:
            detail = "\n".join(str(message) for message in blocking)
            raise CommandError(f"Runtime system checks failed:\n{detail}")
        warning_count = sum(message.level >= checks.WARNING for message in visible)
        self.stdout.write(
            self.style.SUCCESS(
                "RUNTIME_PREPARE_OK "
                f"checks={len(visible)} warnings={warning_count} "
                f"silenced={len(messages) - len(visible)}"
            )
        )
