from django.apps import AppConfig


class HrStructureConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "hr_structure"
    verbose_name = "HR Structure (HR02)"

    def ready(self) -> None:
        super().ready()
        from django.urls import include, path

        from horilla.urls import urlpatterns

        urlpatterns.append(
            path("hr/structure/", include("hr_structure.urls")),
        )
        urlpatterns.append(
            path("", include("hr_structure.api.urls")),
        )
