"""
hr_external/services/category_service.py —— HrExternalCategory 初始化与读取（S1）。

内置默认集按 tenant 惰性注入（ensure_default_categories），避免数据迁移跨校共享。
默认值仅建议（docs/hr/HR08_EXTERNAL_CATEGORY_MATRIX.md），学校可改；
禁止配置掉：tenant 隔离、agreement gate、audit、access expiry、version、exit/revoke。
"""

from __future__ import annotations

from typing import Optional

from django.db import transaction

from hr_external.constants import ExternalWorkerCategory
from hr_external.models import HrExternalCategory

# (code, name, requires_open_selection, requires_ethics_review, requires_teacher_qualification,
#  requires_industry_experience, default_engagement_months, allow_multiple_assignments,
#  allow_teaching, allow_research, agreement_requirement)
DEFAULT_CATEGORY_POLICY = (
    ("PART_TIME_TEACHER", "兼职教师", False, True, True, False, 12, True, True, False, "REQUIRED_BEFORE_ACTIVATION"),
    ("EXTERNAL_TEACHER", "外聘教师", False, True, True, False, 12, True, True, False, "REQUIRED_BEFORE_ACTIVATION"),
    ("INDUSTRY_ADJUNCT", "产业兼职教师", True, True, False, True, 12, True, True, True, "REQUIRED_BEFORE_ACTIVATION"),
    ("INDUSTRY_PROFESSOR", "产业教授", True, True, False, True, 24, True, True, True, "REQUIRED_BEFORE_ACTIVATION"),
    ("SKILL_MASTER", "技能大师", False, True, False, True, 24, True, False, False, "REQUIRED_BEFORE_ACTIVATION"),
    ("INDUSTRY_MENTOR", "产业导师", False, True, False, True, 12, True, False, True, "REQUIRED_BEFORE_ACTIVATION"),
    ("VISITING_PROFESSOR", "客座教授", False, True, False, False, 12, True, False, True, "REQUIRED_BEFORE_ACTIVATION"),
    ("GUEST_PROFESSOR", "讲座教授", False, True, False, False, 12, True, False, True, "REQUIRED_BEFORE_ACTIVATION"),
    ("HONORARY_TITLE", "荣誉/名誉称号", False, True, False, False, None, False, False, False, "NOT_REQUIRED"),
    ("EXTERNAL_EXPERT", "外聘专家", False, True, False, True, 12, True, False, True, "REQUIRED_BEFORE_ACTIVATION"),
    ("PRACTICE_INSTRUCTOR", "实践教学指导教师", False, True, False, True, 12, True, True, False, "REQUIRED_BEFORE_ACTIVATION"),
    ("RETIRED_REHIRE_EXTERNAL", "退休返聘（外聘）", False, True, False, False, 12, True, False, False, "REQUIRED_BEFORE_ACTIVATION"),
    ("PROJECT_EXPERT", "项目专家", False, True, False, True, None, True, False, True, "REQUIRED_BEFORE_ACTIVATION"),
    ("OTHER", "其他", False, True, False, False, None, True, False, False, "REQUIRED_BEFORE_ACTIVATION"),
)


class CategoryService:
    @transaction.atomic
    def ensure_default_categories(self, tenant_id: int) -> int:
        """确保 tenant 拥有内置默认类别集（幂等）。返回本次新增数量。"""
        existing = set(
            HrExternalCategory.objects.filter(tenant_id=tenant_id).values_list("code", flat=True)
        )
        created = 0
        for policy in DEFAULT_CATEGORY_POLICY:
            code = policy[0]
            if code in existing:
                continue
            self._create_category(tenant_id, *policy)
            created += 1
        return created

    def _create_category(self, tenant_id: int, *policy) -> HrExternalCategory:
        (
            code,
            name,
            requires_open_selection,
            requires_ethics_review,
            requires_teacher_qualification,
            requires_industry_experience,
            default_engagement_months,
            allow_multiple_assignments,
            allow_teaching,
            allow_research,
            agreement_requirement,
        ) = policy
        return HrExternalCategory.objects.create(
            tenant_id=tenant_id,
            code=code,
            name=name,
            is_system_builtin=True,
            requires_open_selection=requires_open_selection,
            requires_ethics_review=requires_ethics_review,
            requires_teacher_qualification=requires_teacher_qualification,
            requires_industry_experience=requires_industry_experience,
            default_engagement_months=default_engagement_months,
            allow_multiple_assignments=allow_multiple_assignments,
            allow_teaching=allow_teaching,
            allow_research=allow_research,
            agreement_requirement=agreement_requirement,
        )

    def get_category(self, tenant_id: int, code: str) -> Optional[HrExternalCategory]:
        return (
            HrExternalCategory.objects.filter(tenant_id=tenant_id, code=code, is_active=True)
            .first()
        )

    def list_categories(self, tenant_id: int, *, include_inactive: bool = False):
        qs = HrExternalCategory.objects.filter(tenant_id=tenant_id)
        if not include_inactive:
            qs = qs.filter(is_active=True)
        return qs.order_by("code")


# 合法性检查：内置 code 必须都在 ExternalWorkerCategory 枚举内
assert set(p[0] for p in DEFAULT_CATEGORY_POLICY) == {
    c.value for c in ExternalWorkerCategory
}, "DEFAULT_CATEGORY_POLICY 与 ExternalWorkerCategory 枚举不一致"
