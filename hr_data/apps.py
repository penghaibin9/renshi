from django.apps import AppConfig


class HrDataConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "hr_data"
    verbose_name = "HR18 人事数据中心"

    def ready(self):
        from . import authority_registry  # noqa: F401
