from django.apps import AppConfig

from .module_contract import MODULE_CODE, MODULE_NAME


class HrStaffConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "hr_staff"
    verbose_name = f"{MODULE_NAME} ({MODULE_CODE})"

    def ready(self):
        # Registry-only import. No business writes are allowed during startup.
        from . import authority_registry  # noqa: F401
