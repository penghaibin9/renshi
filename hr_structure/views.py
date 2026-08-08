"""
hr_structure/views.py

HR02 页面视图（薄模板，数据走 JSON API）。
"""

from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def hr_organizations(request):
    """HR02-01 组织机构页面。"""
    return render(request, "hr/structure/organizations.html")
