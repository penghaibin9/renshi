"""
hr_staff/models/mapping.py —— 账号解耦 / 外部身份映射 / Legacy 投影状态（总册 §8.5 / §52.1）。

原则：
- HrStaffMaster 1 --- 0..n HrAccountLink --- Auth User/SSO；
- 人员可以尚未开账号、账号停用但人员历史仍在、更换账号、离职后账号回收但主档永久保留；
- authority model save() 禁止自动创建密码账号。
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _


class HrAccountLink(models.Model):
    class LinkStatus(models.TextChoices):
        ACTIVE = "ACTIVE", _("Active")
        SUSPENDED = "SUSPENDED", _("Suspended")
        UNLINKED = "UNLINKED", _("Unlinked")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    staff_id = models.ForeignKey(
        "hr_staff.HrStaffMaster", on_delete=models.PROTECT, related_name="account_links"
    )
    auth_user_id = models.BigIntegerField(null=True, blank=True)  # HorillaUser.id（仅映射，非 FK 耦合）
    auth_identifier = models.CharField(max_length=254, blank=True, default="")  # username/SSO subject
    link_status = models.CharField(
        max_length=16, choices=LinkStatus.choices, default=LinkStatus.ACTIVE
    )
    linked_at = models.DateTimeField(null=True, blank=True)
    unlinked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("HR Account Link")
        verbose_name_plural = _("HR Account Links")
        indexes = [
            models.Index(fields=["tenant_id", "staff_id", "link_status"]),
            models.Index(fields=["tenant_id", "auth_identifier"]),
            models.Index(fields=["tenant_id", "auth_user_id", "link_status"],
                         name="hr_account_tenant_user_status"),
        ]

    def __str__(self):
        return f"staff={self.staff_id.staff_no} link={self.link_status}"


class HrExternalIdentityMapping(models.Model):
    """外部系统身份映射（SSO/数字校园/教务等）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    staff_id = models.ForeignKey(
        "hr_staff.HrStaffMaster", on_delete=models.PROTECT, related_name="external_identities"
    )
    system_code = models.CharField(max_length=64)
    external_subject = models.CharField(max_length=254)
    mapping_status = models.CharField(max_length=16, default="ACTIVE")
    valid_from = models.DateField(null=True, blank=True)
    valid_to = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("HR External Identity Mapping")
        verbose_name_plural = _("HR External Identity Mappings")
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "system_code", "external_subject"],
                name="uniq_hr_external_identity_scope",
            ),
        ]

    def __str__(self):
        return f"{self.system_code}:{self.external_subject}"


class HrLegacyProjectionState(models.Model):
    """Legacy → authority 投影状态（单向；reconciliation 依据）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    staff_id = models.ForeignKey(
        "hr_staff.HrStaffMaster", on_delete=models.PROTECT, related_name="legacy_projection_states"
    )
    legacy_employee_id = models.BigIntegerField(db_index=True)
    last_projected_at = models.DateTimeField(null=True, blank=True)
    projection_hash = models.CharField(max_length=64, blank=True, default="")
    last_reconciled_at = models.DateTimeField(null=True, blank=True)
    mismatch_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("HR Legacy Projection State")
        verbose_name_plural = _("HR Legacy Projection States")
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "legacy_employee_id"],
                name="uniq_hr_legacy_projection_tenant_emp",
            ),
        ]

    def __str__(self):
        return f"staff={self.staff_id.staff_no} emp={self.legacy_employee_id}"
