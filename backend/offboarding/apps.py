from django.apps import AppConfig
from django.conf import settings


class OffboardingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "offboarding"

    def ready(self):
        settings.APPS.append("offboarding")
        super().ready()
