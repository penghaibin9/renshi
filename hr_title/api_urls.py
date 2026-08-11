from django.urls import path
from . import api

app_name = "hr_title_api"
urlpatterns = [
    path("dashboard/", api.dashboard, name="dashboard"),
]
