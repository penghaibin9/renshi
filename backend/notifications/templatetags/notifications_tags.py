"""Django notifications template tags file"""

import re

from django.template import Library
from django.urls import reverse
from django.utils.html import escapejs, format_html

register = Library()
_CALLBACK_NAME = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*(?:\.[A-Za-z_$][A-Za-z0-9_$]*)*$")
_CSS_CLASS_NAME = re.compile(r"^[A-Za-z_-][A-Za-z0-9_-]*$")


@register.simple_tag(takes_context=True)
def notifications_unread(context):
    user = user_context(context)
    if not user:
        return ""
    return user.notifications.unread().count()


@register.filter
def has_notification(user):
    if user:
        return user.notifications.unread().exists()
    return False


@register.simple_tag
def register_notify_callbacks(
    badge_class="live_notify_badge",
    menu_class="live_notify_list",
    refresh_period=15,
    callbacks="",
    api_name="list",
    fetch=5,
):
    try:
        refresh_period = max(1, min(int(refresh_period), 3600)) * 1000
        fetch = max(1, min(int(fetch), 100))
    except (TypeError, ValueError):
        return ""
    if not _CSS_CLASS_NAME.fullmatch(str(badge_class)):
        badge_class = "live_notify_badge"
    if not _CSS_CLASS_NAME.fullmatch(str(menu_class)):
        menu_class = "live_notify_list"

    if api_name == "list":
        api_url = reverse("notifications:live_unread_notification_list")
    elif api_name == "count":
        api_url = reverse("notifications:live_unread_notification_count")
    else:
        return ""

    script = format_html(
        """
<script>
var notify_badge_class = "{}";
var notify_menu_class = "{}";
var notify_api_url = "{}";
var notify_fetch_count = {};
var notify_unread_url = "{}";
var notify_mark_all_unread_url = "{}";
var notify_refresh_period = {};
""",
        escapejs(badge_class),
        escapejs(menu_class),
        escapejs(api_url),
        fetch,
        escapejs(reverse("notifications:unread")),
        escapejs(reverse("notifications:mark_all_as_read")),
        refresh_period,
    )

    for callback in callbacks.split(","):
        callback = callback.strip()
        if callback and _CALLBACK_NAME.fullmatch(callback):
            script += format_html("register_notifier({});\n", escapejs(callback))

    return script + format_html("</script>")


@register.simple_tag(takes_context=True)
def live_notify_badge(context, *args, badge_class="live_notify_badge", **kwargs):
    user = user_context(context)
    if not user:
        return ""

    return format_html(
        "<span class='{}'>{}</span>",
        badge_class,
        user.notifications.unread().count(),
    )


@register.simple_tag
def live_notify_list(list_class="live_notify_list"):
    return format_html(
        "<ul class='{}'></ul>",
        list_class,
    )


def user_context(context):
    request = context.get("request")
    if not request:
        return None

    user = request.user
    if not user.is_authenticated:
        return None

    return user
