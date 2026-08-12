from django.urls import path
from . import views

app_name = "hr_data"
urlpatterns = [
    path("", views.workspace, name="overview"),
    path("metrics/", views.workspace, {"section": "metrics"}, name="metrics"),
    path("population/", views.workspace, {"section": "population"}, name="population"),
    path("as-of/", views.workspace, {"section": "asof"}, name="asof"),
    path("quality/", views.workspace, {"section": "quality"}, name="quality"),
    path("exchange/", views.workspace, {"section": "exchange"}, name="exchange"),
    path("submissions/", views.workspace, {"section": "submissions"}, name="submissions"),
    path("corrections/", views.workspace, {"section": "corrections"}, name="corrections"),
]
