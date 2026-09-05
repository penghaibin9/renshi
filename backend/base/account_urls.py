"""Canonical account routes; registered before the legacy business URL graph.

Keep public paths and reverse names unchanged, like base.settings_urls. The
legacy Employee-only account callbacks are not selected by URL resolution.
"""

from django.urls import path

from base import account_views

urlpatterns = [
    path("", account_views.home, name="home-page"),
    path("login/", account_views.login_user, name="login"),
    path("notifications/", account_views.notifications, name="notifications"),
    path("all-notifications/", account_views.all_notifications, name="all-notifications"),
]
