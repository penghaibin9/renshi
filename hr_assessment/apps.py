from django.apps import AppConfig


class HrAssessmentConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "hr_assessment"
    verbose_name = "HR12 年度与聘期考核 (Assessment Authority)"

    def ready(self) -> None:
        # Signals are lifecycle hooks and belong in AppConfig.ready(); URLs do not.
        from hr_assessment import signals  # noqa: F401
