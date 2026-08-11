from django.urls import path
from . import api

app_name = "hr_self_api"
urlpatterns = [path("dashboard/", api.dashboard, name="dashboard")]
