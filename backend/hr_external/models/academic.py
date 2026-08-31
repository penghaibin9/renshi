"""
hr_external/models/academic.py —— HrExternalAcademicIdentity 教务教师身份（S6，总册 §96/§97）。

- external_teacher_no：HR08 tenant-scoped 编号（§17）；
- academic_teacher_id：教务侧教师号（由教务分配，Provider 占位）；
- valid_from/valid_to 绑定 Engagement 期限；状态机 PENDING/ACTIVE/SUSPENDED/EXPIRED/REVOKED。
- HR08 不复制完整教务主表；本表只保存"教务身份同步意图与状态"。
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from hr_external.constants import AcademicIdentityStatus


class HrExternalAcademicIdentity(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    engagement_id = models.ForeignKey(
        "hr_external.HrExternalEngagement",
        on_delete=models.PROTECT,
        related_name="academic_identities",
    )
    external_teacher_no = models.CharField(max_length=32)
    academic_teacher_id = models.CharField(max_length=64, blank=True, default="")
    valid_from = models.DateField()
    valid_to = models.DateField(null=True, blank=True)
    status = models.CharField(
        max_length=16,
        choices=AcademicIdentityStatus.choices,
        default=AcademicIdentityStatus.PENDING,
        db_index=True,
    )
    last_sync_at = models.DateTimeField(null=True, blank=True)
    drift_note = models.CharField(max_length=512, blank=True, default="")
    version = models.BigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("HR External Academic Identity")
        verbose_name_plural = _("HR External Academic Identities")
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "engagement_id"],
                name="uniq_hr_external_academic_eng",
            ),
            models.CheckConstraint(
                condition=models.Q(version__gte=1),
                name="hex_academic_version_gte_1",
            ),
        ]
        indexes = [
            models.Index(
                fields=["tenant_id", "status"],
                name="hex_academic_status_idx",
            ),
            models.Index(
                fields=["tenant_id", "academic_teacher_id"],
                name="hex_academic_teacher_idx",
            ),
        ]

    def __str__(self):
        return f"[{self.tenant_id}] {self.external_teacher_no} -> {self.academic_teacher_id} ({self.status})"
