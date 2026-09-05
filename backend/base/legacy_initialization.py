"""Retire the old installation wizard's HTTP writers as one closed boundary.

These exact public paths are kept so old bookmarks and integrations fail
explicitly instead of falling through to legacy callbacks. The former child
handlers could create a superuser/company or delete structure records without
rechecking the installation parent. They must not be a second school-provisioner.

Initial platform credentials are established by the deployment operator's
management command. School records are configured through the authorized
platform and school services, never by reopening this wizard with DEBUG.
"""

from django.http import JsonResponse
from django.urls import path
from django.views.decorators.cache import never_cache


@never_cache
def retired_initialization(request, **kwargs):
    """Do not read submitted credentials, discover tenants, or invoke a writer."""
    return JsonResponse(
        {
            "error": {
                "code": "LEGACY_INITIALIZATION_RETIRED",
                "message": "旧安装向导已停用。平台初始账号由部署管理员配置；学校资料请通过学校管理中心办理。",
            }
        },
        status=410,
    )


ROUTES = (
    ("initialize-database/", "initialize-database"),
    ("load-demo-database/", "load-demo-database"),
    ("initialize-database-user/", "initialize-database-user"),
    ("initialize-database-company/", "initialize-database-company"),
    ("initialize-database-department/", "initialize-database-department"),
    ("initialize-department-edit/<int:obj_id>/", "initialize-department-edit"),
    ("initialize-department-delete/<int:obj_id>/", "initialize-department-delete"),
    ("initialize-database-job-position/", "initialize-database-job-position"),
    ("initialize-job-position-edit/<int:obj_id>/", "initialize-job-position-edit"),
    ("initialize-job-position-delete/<int:obj_id>/", "initialize-job-position-delete"),
)

urlpatterns = [path(route, retired_initialization, name=name) for route, name in ROUTES]
