"""HR12 Assessment — 页面视图（S1 占位，后续 S2-S9 逐步添加业务视图）。"""

from django.http import JsonResponse

from hr_assessment.api.response import api_success


def index(request):
    """Assessment 首页占位（S1 骨架）。后续 S2 替换为完整 Policy Center。"""
    return JsonResponse(
        api_success(
            data={
                "module": "hr_assessment",
                "stage": "S1",
                "status": "foundation",
                "message": "HR12 Assessment Authority — 基础骨架已搭建。"
                "S2 起施工 Policy/Goal/Annual/Term/Ethics。",
            },
            request_id=getattr(request, "request_id", ""),
        )
    )
