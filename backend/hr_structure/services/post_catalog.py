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

from django.db import transaction

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
            validity_from=validity_from or date.today(),
            version_no=1,
            status=HrPostCatalogVersion.Status.ACTIVE,
            **kwargs,
        )
        return catalog

    @transaction.atomic
    def new_version(self, catalog, *, name, category=None, reason="", **kwargs) -> HrPostCatalogVersion:
        """重要语义变化创建新版本（禁止直接破坏性修改旧版本）。"""
        latest = catalog.versions.order_by("-version_no").first()
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
        return HrPostCatalogVersion.objects.create(
            catalog_id=catalog,
            tenant_id=self.scope.tenant_id,
            name=name,
            category=category or latest.category,
            subcategory=kwargs.pop("subcategory", latest.subcategory if latest else ""),
            validity_from=kwargs.pop("validity_from", date.today()),
            version_no=next_no,
            status=HrPostCatalogVersion.Status.ACTIVE,
            **kwargs,
        )
