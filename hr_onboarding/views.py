"""
hr_onboarding/views.py

HR05 页面视图（Django Template 渲染，数据走 JSON API，模板薄）。
S1 阶段：待报到占位页（S3 填充数据源）。
"""

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from hr_onboarding.permissions import require_hr05_permission


@login_required
@require_hr05_permission("hr05.case.view")
def hr05_prehires(request):
    """HR05-01 待报到人员列表（S1 占位；S3 起读 HrOnboardingCase 权威数据）。"""
    return render(request, "hr/onboarding/prehires/list.html")
