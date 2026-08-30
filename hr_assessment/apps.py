from django.apps import AppConfig

from .module_contract import MODULE_CODE, MODULE_NAME


class HrAssessmentConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "hr_assessment"
    verbose_name = f"{MODULE_NAME} ({MODULE_CODE})"

    def ready(self):
        # Signal hooks are startup lifecycle only. URL registration belongs to horilla.urls.
        from . import signals  # noqa: F401
        from .legacy.write_seal import install_pms_write_seal

        install_pms_write_seal()
