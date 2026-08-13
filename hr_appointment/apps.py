from django.apps import AppConfig


class HrAppointmentConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "hr_appointment"
    verbose_name = "HR14 岗位聘任"

    def ready(self):
        # Large authority subdomains stay split into focused model modules.
        # Importing here registers model classes and runtime immutability guards;
        # it performs no database queries or startup writes.
        from . import freeze_guards, population_models, term_models  # noqa: F401
