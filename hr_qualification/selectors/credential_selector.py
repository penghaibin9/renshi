"""
hr_qualification/selectors/credential_selector.py —— 资格查询选择器。

总册 §142：WHERE → COUNT → ORDER → PAGE，禁止先分页再 Python 过滤。
所有 credential 详情读取必须显式 tenant scope，UUID 不能成为跨租户访问凭证。
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import date
from typing import Any

from django.core.paginator import Paginator

from hr_qualification.models import HrCredentialCatalogItem, HrPersonCredential


class CredentialSelector:
    """证书查询选择器。"""

    @staticmethod
    def list_credentials(
        tenant_id: int,
        person_id: uuid.UUID | None = None,
        staff_master_id: uuid.UUID | None = None,
        category: str | None = None,
        catalog_item_id: uuid.UUID | None = None,
        status: str | None = None,
        verification_status: str | None = None,
        expires_before: date | None = None,
        expires_after: date | None = None,
        is_double_teacher_evidence: bool | None = None,
        search_name: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> dict[str, Any]:
        """分页列表查询。"""
        qs = HrPersonCredential.objects.filter(tenant_id=tenant_id)

        if person_id:
            qs = qs.filter(person_id=person_id)
        if staff_master_id:
            qs = qs.filter(staff_master_id=staff_master_id)
        if catalog_item_id:
            qs = qs.filter(catalog_item_id=catalog_item_id)
        if category:
            qs = qs.filter(catalog_item_id__category=category)
        if status:
            qs = qs.filter(status=status)
        if verification_status:
            qs = qs.filter(current_verification_status=verification_status)
        if expires_before:
            qs = qs.filter(valid_to__lte=expires_before)
        if expires_after:
            qs = qs.filter(valid_to__gte=expires_after)
        if search_name:
            qs = qs.filter(credential_name_snapshot__icontains=search_name)

        qs = qs.select_related("catalog_item_id").order_by("-created_at")

        total = qs.count()
        paginator = Paginator(qs, page_size)
        page_obj = paginator.get_page(page)

        return {
            "items": list(page_obj.object_list),
            "total": total,
            "page": page,
            "page_size": page_size,
            "has_next": page_obj.has_next(),
            "has_previous": page_obj.has_previous(),
            "num_pages": paginator.num_pages,
        }

    @staticmethod
    def get_detail(
        *,
        tenant_id: int,
        credential_id: uuid.UUID,
    ) -> HrPersonCredential:
        return (
            HrPersonCredential.objects.select_related(
                "catalog_item_id", "person_id", "staff_master_id"
            ).get(id=credential_id, tenant_id=tenant_id)
        )

    @staticmethod
    def exact_match_by_no(tenant_id: int, certificate_no: str) -> HrPersonCredential | None:
        """证号精确匹配（需权限受控）。"""
        no_hash = hashlib.sha256(certificate_no.encode()).hexdigest()
        return (
            HrPersonCredential.objects.filter(
                tenant_id=tenant_id, certificate_no_hash=no_hash
            )
            .select_related("catalog_item_id")
            .first()
        )

    @staticmethod
    def list_catalog_items(
        tenant_id: int | None = None,
        category: str | None = None,
        active_only: bool = True,
    ) -> list[HrCredentialCatalogItem]:
        """资格目录列表（系统级 + 租户扩展）。"""
        qs = HrCredentialCatalogItem.objects.filter(
            tenant_id=tenant_id
        ) | HrCredentialCatalogItem.objects.filter(tenant_id=None)

        if category:
            qs = qs.filter(category=category)
        if active_only:
            qs = qs.filter(status="ACTIVE")

        return list(qs.order_by("category", "code"))
