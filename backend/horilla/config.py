"""
horilla/config.py

Horilla app configurations
"""

import importlib
import logging

from django.apps import apps
from django.conf import settings
from django.contrib.auth.context_processors import PermWrapper

from horilla.legacy_hr_cutover import RETIRED_LEGACY_HR_APPS

logger = logging.getLogger(__name__)


def get_apps_in_base_dir():
    """Return only active sidebar providers after the HR cutover.

    payroll/offboarding/report remain installed as read-only legacy data sources,
    but their sidebars reverse retired writer URLs. Hiding them here prevents
    navigation from resurrecting a second formal Authority while canonical
    HR15/HR16/HR18 own the live UI/API surfaces.
    """
    return [app for app in settings.SIDEBARS if app not in RETIRED_LEGACY_HR_APPS]


def import_method(accessibility):
    module_path, method_name = accessibility.rsplit(".", 1)
    module = __import__(module_path, fromlist=[method_name])
    accessibility_method = getattr(module, method_name)
    return accessibility_method


ALL_MENUS = {}


def sidebar(request):

    user = getattr(request, "user", None)
    request.MENUS = []

    # These providers belong to the legacy Employee UI. A valid school account
    # may configure its school before personnel records exist; calling legacy
    # project/attendance accessibility functions for it would crash every page,
    # including login and permission-denied rendering. Canonical HR navigation
    # and the settings registry keep their independent permission checks.
    if (
        user is None
        or user.is_anonymous
        or getattr(user, "employee_get", None) is None
    ):
        return []

    base_dir_apps = get_apps_in_base_dir()
    MENUS = request.MENUS

    for app in base_dir_apps:
        if apps.is_installed(app):
            try:
                sidebar = importlib.import_module(app + ".sidebar")

            except Exception as e:
                logger.error(e)
                continue

            if sidebar:
                accessibility = None
                if getattr(sidebar, "ACCESSIBILITY", None):
                    accessibility = import_method(sidebar.ACCESSIBILITY)

                if hasattr(sidebar, "MENU") and (
                    not accessibility
                    or accessibility(
                        request,
                        sidebar.MENU,
                        PermWrapper(user),
                    )
                ):
                    MENU = {}
                    MENU["menu"] = sidebar.MENU
                    MENU["app"] = app
                    MENU["img_src"] = sidebar.IMG_SRC
                    MENU["submenu"] = []
                    MENUS.append(MENU)
                    for submenu in sidebar.SUBMENUS:

                        accessibility = None

                        if submenu.get("accessibility"):
                            accessibility = import_method(submenu["accessibility"])
                        redirect: str = submenu["redirect"]
                        redirect = redirect.split("?")
                        submenu["redirect"] = redirect[0]

                        if not accessibility or accessibility(
                            request,
                            submenu,
                            PermWrapper(user),
                        ):
                            MENU["submenu"].append(submenu)

    session = getattr(request, "session", None)
    if session is not None:
        ALL_MENUS[session.session_key] = MENUS
    return MENUS


def get_MENUS(request):
    # Rebuild at most once per request — accessibility checks hit the DB.
    cached = getattr(request, "_horilla_menus", None)
    if cached is not None:
        return {"sidebar": cached}

    session = getattr(request, "session", None)
    if session is not None:
        ALL_MENUS[session.session_key] = []

    menus = sidebar(request)
    if session is not None:
        menus = ALL_MENUS.get(session.session_key, menus)

    menus = menus or []
    request._horilla_menus = menus
    return {"sidebar": menus}


def load_ldap_settings():
    """
    Fetch LDAP settings dynamically from the database after Django is ready.
    """
    try:
        from django.db import connection

        from horilla_ldap.models import LDAPSettings

        # Ensure DB is ready before querying
        if not connection.introspection.table_names():
            logger.warning("LDAP settings table is unavailable; using defaults")
            return settings.DEFAULT_LDAP_CONFIG

        ldap_config = LDAPSettings.objects.first()
        if ldap_config:
            return {
                "LDAP_SERVER": ldap_config.ldap_server,
                "BIND_DN": ldap_config.bind_dn,
                "BIND_PASSWORD": ldap_config.bind_password,
                "BASE_DN": ldap_config.base_dn,
            }
    except Exception:
        logger.warning("Could not load LDAP settings; using defaults", exc_info=True)
        return settings.DEFAULT_LDAP_CONFIG  # Return default on error

    return settings.DEFAULT_LDAP_CONFIG  # Fallback in case of an issue
