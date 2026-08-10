from django.apps import AppConfig

from .module_contract import MODULE_CODE, MODULE_NAME


class Hr10DevelopmentConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "hr10_development"
    verbose_name = f"{MODULE_NAME} ({MODULE_CODE})"
