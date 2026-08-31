"""App configuration for the retired legacy payroll data source."""

from django.apps import AppConfig
from django.conf import settings


class PayrollConfig(AppConfig):
    """Keep legacy payroll models installed without activating legacy writers."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "payroll"

    def ready(self) -> None:
        ready = super().ready()
        # Cutover contract: payroll remains installed for tenant-safe read-only
        # reconciliation/projection only. Importing payroll.scheduler would
        # start background jobs that create Payslip / mutate Contract, while
        # importing payroll.signals would create legacy Contract rows from
        # EmployeeWorkInformation saves. Neither writer may be activated after
        # FREEZE_LEGACY_FORMAL_WRITES.
        if "payroll" not in settings.APPS:
            settings.APPS.append("payroll")
        return ready
