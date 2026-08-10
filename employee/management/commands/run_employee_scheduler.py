from django.core.management.base import BaseCommand

from employee.scheduler import build_scheduler


class Command(BaseCommand):
    help = "Run the dedicated employee scheduler process (tenant-aware)."

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS("Starting dedicated employee scheduler"))
        scheduler = build_scheduler(blocking=True)
        try:
            scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            self.stdout.write("Employee scheduler stopped")
