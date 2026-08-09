"""
hr_changes/views.py —— HR06 页面视图（S1 占位；S3 起逐模块替换）。
"""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse


@login_required
def change_center(request):
    return HttpResponse("HR06 人事异动中心（S1 占位，S3 施工后提供完整页面）")
