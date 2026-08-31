from django.apps import AppConfig

from .module_contract import MODULE_CODE, MODULE_NAME


class HrChangesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "hr_changes"
    verbose_name = f"{MODULE_NAME} ({MODULE_CODE})"

    def ready(self):
        from . import authority_registry  # noqa: F401
