from django.apps import AppConfig

from .module_contract import MODULE_CODE, MODULE_NAME


class HrStructureConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "hr_structure"
    verbose_name = f"{MODULE_NAME} ({MODULE_CODE})"

    def ready(self):
        # Registration only; no data writes are allowed during application startup.
        from . import authority_registry  # noqa: F401
