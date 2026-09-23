from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth.models import Group

from base.models import Company
from base.system_admin_health import build_system_admin_health
from employee.models import Employee
from horilla_auth.models import HorillaUser


class Command(BaseCommand):
    help = "Run a secret-free standalone-school system-management readiness check."

    def add_arguments(self, parser):
        parser.add_argument(
            "--json",
            action="store_true",
            dest="as_json",
            help="Print machine-readable JSON before applying the blocker exit gate.",
        )

    def handle(self, *args, **options):
        companies = Company.objects.order_by("id")
        school = companies.first() if companies.count() == 1 else None
        employees = Employee.objects.all()
        if school is not None:
            employees = employees.filter(employee_work_info__company_id=school)
        employees = employees.distinct()
        user_ids = list(
            employees.exclude(employee_user_id=None).values_list(
                "employee_user_id", flat=True
            )
        )
        users = HorillaUser.objects.filter(id__in=user_ids)
        metrics = {
            "employees": employees.count(),
            "active_accounts": users.filter(is_active=True).count(),
            "inactive_accounts": users.filter(is_active=False).count(),
            "accounts_without_role": users.filter(groups__isnull=True).distinct().count(),
            "direct_permission_accounts": users.filter(
                user_permissions__isnull=False
            ).distinct().count(),
            "roles": Group.objects.filter(user__id__in=user_ids).distinct().count(),
            "superusers": users.filter(is_superuser=True, is_active=True).count(),
        }
        health = build_system_admin_health(
            selected_company=str(school.pk) if school else None,
            metrics=metrics,
        )
        payload = {
            "status": "BLOCKED" if health["blocker_count"] else "READY_FOR_RUNTIME_ACCEPTANCE",
            "mode": health["mode"],
            "school": getattr(health.get("school"), "company", None),
            "metrics": metrics,
            "blocker_count": health["blocker_count"],
            "warning_count": health["warning_count"],
            "checks": health["checks"],
        }
        if options["as_json"]:
            self.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            self.stdout.write(f"mode={health['mode_label']}")
            self.stdout.write(f"school={payload['school'] or '<not-initialized>'}")
            for item in health["checks"]:
                action = f" | next={item['action']}" if item.get("action") else ""
                self.stdout.write(
                    f"[{item['state'].upper()}] {item['title']}: {item['detail']}{action}"
                )
            self.stdout.write(
                f"summary blockers={health['blocker_count']} warnings={health['warning_count']}"
            )
        if health["blocker_count"]:
            raise CommandError(
                "Standalone-school system check is blocked; resolve blocker items before runtime acceptance."
            )
        self.stdout.write(self.style.SUCCESS("SCHOOL_SYSTEM_CHECK_OK"))
