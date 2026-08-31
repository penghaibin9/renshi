from django.apps import AppConfig

from .module_contract import MODULE_CODE, MODULE_NAME


class HrRecruitmentConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "hr_recruitment"
    verbose_name = f"{MODULE_NAME} ({MODULE_CODE})"

    def ready(self):
        from . import authority_registry  # noqa: F401
