"""Canonical account routes; registered before the legacy business URL graph.

Keep public paths and reverse names unchanged, like base.settings_urls. The
legacy Employee-only account callbacks are not selected by URL resolution.
"""

from django.urls import include, path

from base import account_password, account_views

urlpatterns = [
    path("", include("base.legacy_initialization")),
    path("", account_views.home, name="home-page"),
    path("login/", account_views.login_user, name="login"),
    path("change-password/", account_password.change_password, name="change-password"),
    path("notifications/", account_views.notifications, name="notifications"),
    path("all-notifications/", account_views.all_notifications, name="all-notifications"),
    path("get-horilla-installed-apps/", account_views.get_horilla_installed_apps,
         name="get-horilla-installed-apps"),
]
