from django.apps import AppConfig


class HrAppointmentConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "hr_appointment"
    verbose_name = "HR14 岗位聘任"

    def ready(self):
        # HR14 term-governance models are split from the already-large initial
        # appointment authority module. Importing here only registers model
        # classes and runtime immutability guards; it performs no startup writes.
        from . import freeze_guards, term_models  # noqa: F401
