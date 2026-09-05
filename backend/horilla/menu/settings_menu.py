"""Permission-filtered settings menu. Business apps own their registrations."""

from django.contrib.auth.context_processors import PermWrapper
from django.urls import reverse

from horilla.menu.registry import MenuRegistry


class SettingsRegistry(MenuRegistry):
    @staticmethod
    def _item_visible(item, request):
        accessibility = item.get("accessibility", True)
        if callable(accessibility):
            return bool(accessibility(request, item, PermWrapper(request.user)))
        return bool(accessibility)

    @staticmethod
    def _item_sort_key(item):
        order = item.get("order", None)
        if order is None:
            return (1, 0)
        if order >= 0:
            return (0, order)
        return (2, order)

    def _build_entry(self, obj, request):
        visible_items = [
            item for item in getattr(obj, "items", [])
            if self._item_visible(item, request)
        ]
        if not visible_items:
            return None
        return {
            "title": getattr(obj, "title", ""),
            "icon": getattr(obj, "icon", ""),
            "items": sorted(visible_items, key=self._item_sort_key),
        }


settings_registry = SettingsRegistry()


def get_settings_menu(request):
    # Copy the container; never append request-specific entries to the registry.
    entries = list(settings_registry.get_entries(request))
    selected = getattr(request, "session", {}).get("selected_company")
    user = getattr(request, "user", None)
    if (selected not in (None, "", "all") and user
            and getattr(user, "is_authenticated", False)
            and user.has_perm("base.view_company")):
        # Keep the established preferences landing page, bookmarks and browser
        # assertions. The school center is the next explicit settings section.
        entries.insert(min(1, len(entries)), {
            "key": "school-management", "title": "学校管理中心", "icon": "",
            "items": [{"label": "首次配置与学校资料", "url": reverse("school-management")}],
        })
    return entries
