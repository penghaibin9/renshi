from django.apps import AppConfig

from .module_contract import MODULE_CODE, MODULE_NAME


class HrControlCenterConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "hr_control_center"
    verbose_name = f"{MODULE_NAME} ({MODULE_CODE})"

    def ready(self):
        # Registry-only import. HR01 is a read model and performs no startup writes.
        from . import authority_registry  # noqa: F401
