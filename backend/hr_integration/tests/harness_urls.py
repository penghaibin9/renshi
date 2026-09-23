from django.http import HttpResponse
from django.urls import path


def _ok(request, connection_id=None):
    return HttpResponse("ok")

urlpatterns = [
    path("sso/<uuid:connection_id>/callback/", _ok, name="hr-sso-callback"),
]
