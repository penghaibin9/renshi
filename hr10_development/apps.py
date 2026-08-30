from django.apps import AppConfig


class Hr10DevelopmentConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "hr10_development"
    verbose_name = "HR10 培训进修与企业实践"

    def ready(self):
        from .authority_registry import register_authority_definitions

        register_authority_definitions()
