from django.apps import AppConfig


class HrSelfConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "hr_self"
    verbose_name = "HR17 教职工服务"

    def ready(self):
        from . import authority_registry  # noqa: F401
