"""Unify the top-right settings entry with the settings registry.

Historically ``show_section`` carried a second hard-coded permission list while
``SettingsView`` used the dynamic settings registry.  The two sources drifted,
so users could see a gear that opened a 403 or have valid settings without any
entry point.  Install one explicit template-tag override backed by the same
filtered registry used by the settings page.
"""


def settings_menu_visible(context):
    request = context.get("request")
    if request is None:
        return False
    user = getattr(request, "user", None)
    if not user or not getattr(user, "is_authenticated", False):
        return False

    from horilla.menu import get_settings_menu

    return bool(get_settings_menu(request))


def install_settings_visibility_tag():
    """Register the canonical implementation under the legacy tag name."""

    from base.templatetags import basefilters

    basefilters.register.simple_tag(
        takes_context=True,
        name="show_section",
    )(settings_menu_visible)
