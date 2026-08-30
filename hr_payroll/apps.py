from django.apps import AppConfig


class HrPayrollConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "hr_payroll"
    verbose_name = "HR15 薪酬福利"

    def ready(self):
        from . import (  # noqa: F401
            authority_models,
            authority_registry,
            calculation_models,
            statutory_models,
        )
