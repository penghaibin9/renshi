from django.apps import AppConfig

from .module_contract import MODULE_CODE, MODULE_NAME


class HrTimeConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "hr_time"
    verbose_name = f"{MODULE_NAME} ({MODULE_CODE})"

    def ready(self):
        from .authority_registry import register_authority_definitions

        register_authority_definitions()
