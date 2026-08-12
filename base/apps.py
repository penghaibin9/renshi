"""
This module contains the configuration for the 'base' app.
"""

from django.apps import AppConfig, apps
from django.conf import settings


class BaseConfig(AppConfig):
    """
    Configuration class for the 'base' app.
    """

    default_auto_field = "django.db.models.BigAutoField"
    name = "base"

    def ready(self) -> None:
        _install_mysql_schema_compatibility()

        from base import sidebar, signals  # noqa: F401

        super().ready()
        check_for_no_permissions_models()


def _install_mysql_schema_compatibility() -> None:
    """Install the narrow legacy MySQL migration compatibility shim."""
    engine = settings.DATABASES.get("default", {}).get("ENGINE", "")
    if engine != "django.db.backends.mysql":
        return

    from django.db.backends.mysql.base import DatabaseWrapper

    from base.mysql_schema import HorillaMySQLSchemaEditor

    # DatabaseWrapper.SchemaEditorClass is consulted by connection.schema_editor()
    # for both normal deploy migrations and CI fresh-database migrations.
    DatabaseWrapper.SchemaEditorClass = HorillaMySQLSchemaEditor


def check_for_no_permissions_models():

    model_names = set()
    for model in apps.get_models():
        if getattr(model, "_no_permission_model", False):
            model_names.add(model._meta.model_name)

    settings.NO_PERMISSION_MODALS.extend(list(model_names))
