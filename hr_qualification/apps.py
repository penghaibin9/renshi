from django.apps import AppConfig


class HrQualificationConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "hr_qualification"
    verbose_name = "HR09 Qualification & Double Teacher"

    def ready(self):
        # Registry declarations only; startup must never write business data.
        from . import events, permissions  # noqa: F401
