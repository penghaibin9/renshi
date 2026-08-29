"""HR06 collection adapters that keep GET/POST permissions independent."""

from django.views.decorators.http import require_http_methods

from hr_changes.api import changes as changes_api
from hr_changes.api.base import error_response


@require_http_methods(["GET", "POST"])
def change_collection(request):
    """GET requires view; POST keeps the canonical create permission in changes.py."""
    if request.method == "POST":
        return changes_api.change_list(request)
    if not (
        request.user.is_authenticated
        and (request.user.is_superuser or request.user.has_perm("hr.change.view"))
    ):
        return error_response(
            request,
            "PERMISSION_DENIED",
            "无查看异动权限",
            status=403,
        )
    return changes_api.change_list(request)
