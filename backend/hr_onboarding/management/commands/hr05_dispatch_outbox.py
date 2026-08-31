"""
hr05_dispatch_outbox —— 投递 HR05 PENDING outbox 事件。

用法：
  python manage.py hr05_dispatch_outbox [--tenant 1] [--limit 100]
      [--worker-id host-pid] [--lease-seconds 120]

显式 tenant；消费按 eventId 幂等；超限进 FAILED 死信。
"""

from django.core.management.base import BaseCommand

from hr_onboarding.jobs.outbox_dispatcher import dispatch_pending


class Command(BaseCommand):
    help = "投递 HR05 outbox PENDING 事件（幂等/重试/死信）"

    def add_arguments(self, parser):
        parser.add_argument("--tenant", type=int, default=None)
        parser.add_argument("--limit", type=int, default=100)
        parser.add_argument("--worker-id", type=str, default=None)
        parser.add_argument("--lease-seconds", type=int, default=120)

    def handle(self, *args, **options):
        result = dispatch_pending(
            tenant_id=options["tenant"],
            limit=options["limit"],
            worker_id=options["worker_id"],
            lease_seconds=options["lease_seconds"],
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"dispatched={result['dispatched']} retrying={result['retrying']} "
                f"failed={result['failed']} lost={result['lost']} total={result['total']}"
            )
        )
