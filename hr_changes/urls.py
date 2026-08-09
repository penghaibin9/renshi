"""
hr_changes/urls.py —— HR06 页面路由（S1 占位骨架）。

统一前缀 /hr/changes/（由 apps.ready() 挂载）：
- /hr/changes/                        HR06-01 异动申请中心（S3）
- /hr/changes/new                     HR06-01 发起向导（S3）
- /hr/changes/future                  HR06-01 未来生效队列（S3）
- /hr/changes/transfers               HR06-02 校内调动（S4）
- /hr/changes/job-identity            HR06-03 岗位与身份变更（S5）
- /hr/changes/secondments             HR06-04 借调挂职（S6）
- /hr/changes/ledger                  HR06-05 异动台账（S7）

S1 阶段：占位页（避免 404）。
"""

from django.urls import path
from django.views.generic import RedirectView

from hr_changes import views

urlpatterns = [
    path(
        "",
        RedirectView.as_view(pattern_name="hr06-change-center", permanent=False),
    ),
    # S3 挂载点（占位重定向到中心页，S3 替换为真实视图）
    path("changes", views.change_center, name="hr06-change-center"),
    path("new", RedirectView.as_view(pattern_name="hr06-change-center", permanent=False)),
    path("future", RedirectView.as_view(pattern_name="hr06-change-center", permanent=False)),
    path("transfers", RedirectView.as_view(pattern_name="hr06-change-center", permanent=False)),
    path("job-identity", RedirectView.as_view(pattern_name="hr06-change-center", permanent=False)),
    path("secondments", RedirectView.as_view(pattern_name="hr06-change-center", permanent=False)),
    path("ledger", RedirectView.as_view(pattern_name="hr06-change-center", permanent=False)),
]
