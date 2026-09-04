"""Django application configuration for the PMS app."""

import threading

from django.apps import AppConfig
from django.conf import settings
from django.utils.translation import gettext_lazy as _


_automation_lock = threading.Lock()
_automation_initialized = False


def initialize_pms_automation_once(**_kwargs):
    """Load tenant rules after Django startup, once per Web process."""
    global _automation_initialized
    if _automation_initialized:
        return
    with _automation_lock:
        if _automation_initialized:
            return
        from pms.signals import start_automation

        start_automation()
        _automation_initialized = True

class PmsConfig(AppConfig):
    """Configure the legacy-compatible performance app."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "pms"
    verbose_name = _("Performance")

    def ready(self):
        from django.urls import include, path

        from horilla.urls import urlpatterns

        settings.APPS.append("pms")
        urlpatterns.append(
            path("pms/", include("pms.urls")),
        )
        super().ready()
