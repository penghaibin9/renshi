from django.apps import AppConfig


class HrContractsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "hr_contracts"
    verbose_name = "HR07 合同管理"

    def ready(self):
        # Registration only: no hidden business writes at import/startup time.
        from . import events, permissions  # noqa: F401
