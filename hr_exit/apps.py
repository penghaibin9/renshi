from django.apps import AppConfig


class HrExitConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "hr_exit"
    verbose_name = "HR16 退休与离校"

    def ready(self):
        from . import archive_models, archive_registry  # noqa: F401