"""
horilla/config.py

Horilla app configurations
"""

import importlib
import logging

from django.apps import apps
from django.conf import settings
from django.contrib.auth.context_processors import PermWrapper

logger = logging.getLogger(__name__)


def get_apps_in_base_dir():
    return settings.SIDEBARS


def import_method(accessibility):
    module_path, method_name = accessibility.rsplit(".", 1)
    module = __import__(module_path, fromlist=[method_name])
    accessibility_method = getattr(module, method_name)
    return accessibility_method


ALL_MENUS = {}


def sidebar(request):

    base_dir_apps = get_apps_in_base_dir()
    user = getattr(request, "user", None)

    # Normal Django requests get user/session from middleware. Direct view
    # calls (management commands and focused RequestFactory tests) may not.
    # A context processor should degrade to an empty sidebar instead of making
    # template rendering crash merely because middleware was intentionally
    # bypassed.
    if user is None or user.is_anonymous:
        return []

    request.MENUS = []
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
            print("⚠️ Database is empty. Using default LDAP settings.")
            return settings.DEFAULT_LDAP_CONFIG

        ldap_config = LDAPSettings.objects.first()
        if ldap_config:
            return {
                "LDAP_SERVER": ldap_config.ldap_server,
                "BIND_DN": ldap_config.bind_dn,
                "BIND_PASSWORD": ldap_config.bind_password,
                "BASE_DN": ldap_config.base_dn,
            }
    except Exception as e:
        print(f"⚠️ Warning: Could not load LDAP settings ({e})")
        return settings.DEFAULT_LDAP_CONFIG  # Return default on error

    return settings.DEFAULT_LDAP_CONFIG  # Fallback in case of an issue
