from django.apps import AppConfig
from django.conf import settings


class HorillaLdapConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "horilla_ldap"
    verbose_name = "LDAP"

    def ready(self):
        """Register the sidebar provider without doing startup I/O.

        AppConfig.ready() runs for every management command, worker and test
        process, often before migrations have created the LDAP table.  Runtime
        configuration therefore comes from environment-backed Django settings;
        database-backed LDAP settings are read only by explicit LDAP views and
        import commands.
        """
        ready = super().ready()
        if "horilla_ldap" not in settings.APPS:
            settings.APPS.append("horilla_ldap")
        return ready
