from django.apps import AppConfig


class HrStaffConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "hr_staff"
    verbose_name = "HR Staff Master (HR03)"

    def ready(self) -> None:
        super().ready()
        from django.urls import include, path

        from horilla.urls import urlpatterns

        # 页面路由：/hr/staff/（HR03-01 名册入口；迁移期保留 legacy 兼容入口）
        urlpatterns.append(
            path("hr/staff/", include("hr_staff.urls")),
        )
        # API 路由：独立前缀 /api/hr/v1/staff/
        urlpatterns.append(
            path("", include("hr_staff.api.urls")),
        )
