"""
This module contains the configuration for the 'base' app.
"""

from django.apps import AppConfig, apps
from django.conf import settings


LEGACY_WRITE_ROUTER = "horilla.legacy_hr_cutover.LegacyWriteAuthorityRouter"
LEGACY_WRITE_MIDDLEWARE = "horilla.legacy_hr_cutover.LegacyWriteAuthorityMiddleware"
THREAD_LOCAL_MIDDLEWARE = "horilla.horilla_middlewares.ThreadLocalMiddleware"


class BaseConfig(AppConfig):
    """
    Configuration class for the 'base' app.
    """

    default_auto_field = "django.db.models.BigAutoField"
    name = "base"

    def ready(self) -> None:
        _install_legacy_write_authority_core()
        _install_mysql_schema_compatibility()

        from base import production_checks, sidebar, signals  # noqa: F401
        from base.settings_visibility import install_settings_visibility_tag

        # The top-right gear and SettingsView must use the same filtered
        # registry.  Loading sidebar first guarantees all base settings entries
        # exist before the canonical template tag is installed.
        install_settings_visibility_tag()

        super().ready()
        check_for_no_permissions_models()


def _install_legacy_write_authority_core() -> None:
    """Install the final ORM guard and request-context cleanup before serving."""
    routers = list(getattr(settings, "DATABASE_ROUTERS", ()))
    if LEGACY_WRITE_ROUTER not in routers:
        routers.insert(0, LEGACY_WRITE_ROUTER)
        settings.DATABASE_ROUTERS = routers

        # django.db.router is a process-global ConnectionRouter whose `routers`
        # attribute is cached. In long-lived test/app initialization paths it
        # may have been evaluated before AppConfig.ready(); force one safe
        # refresh after extending the setting.
        from django.db import router as django_router

        django_router.__dict__.pop("routers", None)

    middleware = list(getattr(settings, "MIDDLEWARE", ()))
    company_middleware = "base.middleware.CompanyMiddleware"
    company_index = (
        middleware.index(company_middleware)
        if company_middleware in middleware
        else len(middleware)
    )

    if THREAD_LOCAL_MIDDLEWARE not in middleware:
        middleware.insert(company_index, THREAD_LOCAL_MIDDLEWARE)
        company_index += 1

    if LEGACY_WRITE_MIDDLEWARE not in middleware:
        # Keep the exception translator inside the request-context wrapper and
        # adjacent to CompanyMiddleware so the final ORM router always has the
        # exact current request while a generic writer is executing.
        middleware.insert(company_index + 1, LEGACY_WRITE_MIDDLEWARE)

    settings.MIDDLEWARE = middleware


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
