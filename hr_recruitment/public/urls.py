"""
hr_recruitment/public/urls.py

招聘公开门户路由（独立前缀 /recruit/，无登录、无 /hr/ 管理端前缀）。

A0：公开入口由 token 解析学校；禁止客户端传 tenant_id。
"""

from django.urls import path

from hr_recruitment.public import views as public_views

urlpatterns = [
    # 注意：my-applications 必须放在 <str:token> 之前，避免被当作 token 匹配
    path(
        "recruit/my-applications",
        public_views.public_my_applications,
        name="hr04-public-my-applications",
    ),
    path(
        "recruit/<str:token>",
        public_views.public_campaign,
        name="hr04-public-campaign",
    ),
    path(
        "recruit/<str:token>/positions/<str:position_slug>",
        public_views.public_position,
        name="hr04-public-position",
    ),
    path(
        "recruit/<str:token>/apply",
        public_views.public_apply,
        name="hr04-public-apply",
    ),
]
