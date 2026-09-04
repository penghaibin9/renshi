"""
hr_structure/services/post_catalog.py

PostCatalogService —— 岗位目录（总册 12 节）。

原则：
- 已被岗位引用的 catalog 禁止破坏性改类别；
- 重要语义变化创建新版本；
- 禁止删除已使用岗位目录。
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from hr_structure.models import (
    HrPostCatalog,
    HrPostCatalogVersion,
)
from hr_structure.scope import Hr02Scope


class PostCatalogService:
    def __init__(self, scope: Hr02Scope, actor: str = ""):
        self.scope = scope
        self.actor = actor

    @transaction.atomic
    def create_catalog(self, *, stable_code, name, category, subcategory="", validity_from=None, **kwargs) -> HrPostCatalog:
        stable_code = str(stable_code or "").strip()
        name = str(name or "").strip()
        validity_from = validity_from or timezone.localdate()
        if not stable_code or not name:
            raise ValueError("岗位目录编码和名称不能为空")
        if category not in {value for value, _ in HrPostCatalogVersion.Category.choices}:
            raise ValueError("岗位目录类别非法")
        if subcategory and subcategory not in {
            value for value, _ in HrPostCatalogVersion.Subcategory.choices
        }:
            raise ValueError("岗位目录子类别非法")
        self._validate_version_references(kwargs)
        try:
            if Decimal(str(kwargs.get("standard_fte", "1.00"))) <= 0:
                raise InvalidOperation
        except (InvalidOperation, TypeError, ValueError):
            raise ValueError("标准 FTE 必须大于 0")
        catalog = HrPostCatalog.objects.create(
            tenant_id=self.scope.tenant_id,
            stable_code=stable_code,
        )
        HrPostCatalogVersion.objects.create(
            catalog_id=catalog,
            tenant_id=self.scope.tenant_id,
            name=name,
            category=category,
            subcategory=subcategory,
            validity_from=validity_from,
            version_no=1,
            status=HrPostCatalogVersion.Status.ACTIVE,
            **kwargs,
        )
        return catalog

    def _validate_version_references(self, values):
        from hr_structure.models import HrPostGrade, HrPostGradeScheme

        control_mode = values.get(
            "control_mode", HrPostCatalogVersion.ControlMode.POSITION_CONTROL
        )
        if control_mode not in {
            value for value, _ in HrPostCatalogVersion.ControlMode.choices
        }:
            raise ValueError("岗位控制模式非法")
        time_type = values.get("time_type", HrPostCatalogVersion.TimeType.FULL_TIME)
        if time_type not in {
            value for value, _ in HrPostCatalogVersion.TimeType.choices
        }:
            raise ValueError("岗位工时类型非法")

        scheme_id = values.get("grade_scheme_id") or values.get("grade_scheme_id_id")
        if scheme_id and not HrPostGradeScheme.objects.filter(
            tenant_id=self.scope.tenant_id, id=scheme_id, status="ACTIVE"
        ).exists():
            raise ValueError("岗位等级方案不存在、未启用或跨租户")
        for key in ("min_grade_id", "max_grade_id", "default_grade_id"):
            grade_id = values.get(key) or values.get(f"{key}_id")
            if grade_id and not HrPostGrade.objects.filter(
                id=grade_id, scheme_id__tenant_id=self.scope.tenant_id
            ).exists():
                raise ValueError("岗位等级不存在或跨租户")

    @transaction.atomic
    def new_version(self, catalog, *, name, category=None, reason="", **kwargs) -> HrPostCatalogVersion:
        """重要语义变化创建新版本（禁止直接破坏性修改旧版本）。"""
        catalog = HrPostCatalog.objects.select_for_update().filter(
            tenant_id=self.scope.tenant_id, id=catalog.id
        ).first()
        if catalog is None:
            raise ValueError("岗位目录不存在或跨租户")
        latest = catalog.versions.select_for_update().order_by("-version_no").first()
        if latest is None:
            raise ValueError("岗位目录缺少可继承版本")
        validity_from = kwargs.pop("validity_from", timezone.localdate())
        if validity_from < latest.validity_from:
            raise ValueError("新版本生效日不得早于当前版本")
        if catalog.versions.filter(validity_from__gte=validity_from).exclude(
            id=latest.id
        ).exists():
            raise ValueError("已存在同日或未来岗位目录版本")
        next_no = (latest.version_no if latest else 0) + 1
        if category is not None:
            # 已被岗位引用的 catalog 禁止破坏性改类别（总册 12.7）
            if catalog.versions.filter(status="ACTIVE").exclude(category=category).exists():
                # 检查是否有 position 引用当前 ACTIVE 版本
                from hr_structure.models import HrPosition

                if HrPosition.objects.filter(
                    tenant_id=self.scope.tenant_id,
                    post_catalog_version_id__catalog_id=catalog,
                ).exists():
                    raise ValueError("该岗位目录已被岗位引用，禁止破坏性修改类别")
        category = category or latest.category
        subcategory = kwargs.pop("subcategory", latest.subcategory)
        if category not in {value for value, _ in HrPostCatalogVersion.Category.choices}:
            raise ValueError("岗位目录类别非法")
        if subcategory and subcategory not in {
            value for value, _ in HrPostCatalogVersion.Subcategory.choices
        }:
            raise ValueError("岗位目录子类别非法")
        inherited = {
            "grade_scheme_id_id": latest.grade_scheme_id_id,
            "min_grade_id_id": latest.min_grade_id_id,
            "max_grade_id_id": latest.max_grade_id_id,
            "default_grade_id_id": latest.default_grade_id_id,
            "control_mode": latest.control_mode,
            "standard_fte": latest.standard_fte,
            "time_type": latest.time_type,
            "worker_types_json": latest.worker_types_json,
            "responsibilities_text": latest.responsibilities_text,
            "qualification_rule_json": latest.qualification_rule_json,
            "requires_professional_credential": latest.requires_professional_credential,
            "is_special_post": latest.is_special_post,
        }
        inherited.update(kwargs)
        self._validate_version_references(inherited)
        try:
            if Decimal(str(inherited["standard_fte"])) <= 0:
                raise InvalidOperation
        except (InvalidOperation, TypeError, ValueError):
            raise ValueError("标准 FTE 必须大于 0")
        latest.validity_to = validity_from
        latest.save(update_fields=["validity_to"])
        return HrPostCatalogVersion.objects.create(
            catalog_id=catalog,
            tenant_id=self.scope.tenant_id,
            name=str(name or "").strip() or latest.name,
            category=category,
            subcategory=subcategory,
            validity_from=validity_from,
            version_no=next_no,
            status=HrPostCatalogVersion.Status.ACTIVE,
            **inherited,
        )
