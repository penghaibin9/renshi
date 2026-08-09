"""
hr_external/models/profile.py —— HrExternalTeacherProfile 外聘教师档案（S2，总册 §16/§24/§25）。

边界（硬门）：
- 身份根复用 HR03 `hr_staff.HrPerson`（tenant-private）；**严禁**自建 ExternalPerson 第二自然人表（§6.1）。
- Profile 不保存"当前学院/当前课程/当前协议结束日"；这些属于 Engagement/Assignment（§16）。
- external_teacher_no 为 tenant-scoped 独立序列（§17），不是正式员工工号；复用规则由学校决定。
- candidate_pool_status=DO_NOT_ENGAGE 为敏感业务结论：权限严格、必须 reason、普通页面不显示污名化信息（§25）。
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from hr_external.constants import (
    CandidatePoolStatus,
    IdentityVerificationStatus,
    ProfileEthicsStatus,
    SensitivityLevel,
)


class HrExternalTeacherProfile(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    # ---- 身份根：复用 HR03 HrPerson（唯一自然人身份根）----
    person_id = models.ForeignKey(
        "hr_staff.HrPerson",
        on_delete=models.PROTECT,
        related_name="external_profiles",
    )
    external_teacher_no = models.CharField(max_length=32)
    primary_category = models.ForeignKey(
        "hr_external.HrExternalCategory",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="profiles",
    )
    # ---- 来源单位（§16）----
    source_organization_name = models.CharField(max_length=200, blank=True, default="")
    source_organization_type = models.CharField(max_length=64, blank=True, default="")
    source_position_title = models.CharField(max_length=200, blank=True, default="")
    industry_domain = models.CharField(max_length=128, blank=True, default="")
    expertise_tags = models.JSONField(default=list, blank=True)
    # ---- 资质（§16/§10）----
    highest_professional_title = models.CharField(max_length=120, blank=True, default="")
    highest_skill_level = models.CharField(max_length=120, blank=True, default="")
    # 引用 HR09 已核验教师资格事实（Provider 占位；HR09 未交付则为空）
    teacher_qualification_ref = models.CharField(max_length=64, blank=True, default="")
    # ---- 合规状态（§36/§25）----
    ethics_status = models.CharField(
        max_length=24,
        choices=ProfileEthicsStatus.choices,
        default=ProfileEthicsStatus.NONE,
    )
    identity_verification_status = models.CharField(
        max_length=24,
        choices=IdentityVerificationStatus.choices,
        default=IdentityVerificationStatus.UNVERIFIED,
    )
    candidate_pool_status = models.CharField(
        max_length=32,
        choices=CandidatePoolStatus.choices,
        default=CandidatePoolStatus.AVAILABLE,
    )
    # ---- 投影（仅由 service 维护，可从 Engagement 重建）----
    current_engagement_status = models.CharField(
        max_length=24, blank=True, default="", db_index=True
    )
    # ---- 敏感字段等级（00 §36/§127）----
    sensitivity_level = models.CharField(
        max_length=24,
        choices=SensitivityLevel.choices,
        default=SensitivityLevel.RESTRICTED_HR,
    )
    # ---- 治理 ----
    source = models.CharField(max_length=24, default="HR_ENTERED")
    version = models.BigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("HR External Teacher Profile")
        verbose_name_plural = _("HR External Teacher Profiles")
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "external_teacher_no"],
                name="uniq_hr_external_profile_tenant_no",
            ),
            models.UniqueConstraint(
                fields=["tenant_id", "person_id"],
                name="uniq_hr_external_profile_tenant_person",
            ),
            models.CheckConstraint(
                condition=models.Q(version__gte=1),
                name="hr_external_profile_version_gte_1",
            ),
        ]
        indexes = [
            models.Index(
                fields=["tenant_id", "candidate_pool_status"],
                name="hr_external_profile_pool_idx",
            ),
            models.Index(
                fields=["tenant_id", "primary_category"],
                name="hr_external_profile_category_idx",
            ),
            models.Index(
                fields=["tenant_id", "source_organization_name"],
                name="hr_external_profile_source_org_idx",
            ),
        ]

    def __str__(self):
        return f"[{self.tenant_id}] {self.external_teacher_no}"
