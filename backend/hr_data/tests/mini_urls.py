from django.urls import include, path


urlpatterns = [
    path(
        "api/v1/hr/data/",
        include(("hr_data.api_urls", "hr_data_api"), namespace="hr_data_api"),
    ),
    path(
        "hr/data/",
        include(("hr_data.urls", "hr_data"), namespace="hr_data"),
    ),
]
