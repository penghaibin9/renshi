"""
hr_staff/models/education.py —— 第五层背景事实：教育/学位/工作经历（总册 §13）。

原则：
- 多条结构化记录，禁止塞 JSON；
- 学历与学位分开（HrEducationExperience vs HrDegreeRecord），禁止"博士研究生"同时当学历和学位；
- 最高学历只能根据规则/人工确认，不靠"最后一条"；
- 时间校验 end >= start；来源 + verification_status + version。
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from hr_staff.constants import SourceCategory, VerificationStatus


class HrEducationExperience(models.Model):
    """教育经历。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    staff_id = models.ForeignKey(
        "hr_staff.HrStaffMaster", on_delete=models.PROTECT, related_name="education_experiences"
    )
    school_name = models.CharField(max_length=200)
    country_region = models.CharField(max_length=8, blank=True, default="CN")
    education_level = models.CharField(max_length=32)  # 学历层次（博士研究生/硕士研究生/本科/专科…）
    major_name = models.CharField(max_length=200, blank=True, default="")
    study_type = models.CharField(max_length=32, blank=True, default="")  # 全日制/在职/…
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    is_highest_education = models.BooleanField(default=False)
    verification_status = models.CharField(
        max_length=16, choices=VerificationStatus.choices, default=VerificationStatus.UNVERIFIED
    )
    verified_by = models.BigIntegerField(null=True, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    source = models.CharField(
        max_length=24, choices=SourceCategory.choices, default=SourceCategory.HR_ENTERED
    )
    source_domain = models.CharField(max_length=32, blank=True, default="")
    source_business_id = models.CharField(max_length=64, null=True, blank=True)
    version = models.BigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("HR Education Experience")
        verbose_name_plural = _("HR Education Experiences")
        constraints = [
            models.CheckConstraint(
                check=models.Q(end_date__isnull=True)
                | models.Q(start_date__isnull=True)
                | models.Q(end_date__gte=models.F("start_date")),
                name="chk_hr_education_end_gte_start",
            ),
            models.UniqueConstraint(
                fields=["tenant_id", "source_domain", "source_business_id"],
                name="uniq_hr03_education_source_fact",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant_id", "staff_id"]),
        ]

    def __str__(self):
        return f"{self.education_level} {self.school_name}"


class HrDegreeRecord(models.Model):
    """学位信息（与学历分开）。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    staff_id = models.ForeignKey(
        "hr_staff.HrStaffMaster", on_delete=models.PROTECT, related_name="degree_records"
    )
    degree_level = models.CharField(max_length=32)  # 博士/硕士/学士/…
    degree_name = models.CharField(max_length=120, blank=True, default="")
    granting_institution = models.CharField(max_length=200, blank=True, default="")
    major = models.CharField(max_length=200, blank=True, default="")
    awarded_date = models.DateField(null=True, blank=True)
    verification_status = models.CharField(
        max_length=16, choices=VerificationStatus.choices, default=VerificationStatus.UNVERIFIED
    )
    verified_by = models.BigIntegerField(null=True, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    source = models.CharField(
        max_length=24, choices=SourceCategory.choices, default=SourceCategory.HR_ENTERED
    )
    source_domain = models.CharField(max_length=32, blank=True, default="")
    source_business_id = models.CharField(max_length=64, null=True, blank=True)
    version = models.BigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("HR Degree Record")
        verbose_name_plural = _("HR Degree Records")
        indexes = [
            models.Index(fields=["tenant_id", "staff_id"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "source_domain", "source_business_id"],
                name="uniq_hr03_degree_source_fact",
            ),
        ]

    def __str__(self):
        return f"{self.degree_level} {self.degree_name}"


class HrWorkExperience(models.Model):
    """工作经历。"""

    class ExperienceType(models.TextChoices):
        UNIVERSITY = "UNIVERSITY", _("University")
        ENTERPRISE = "ENTERPRISE", _("Enterprise")
        INDUSTRY = "INDUSTRY", _("Industry Organization")
        GOVERNMENT = "GOVERNMENT", _("Government/Public Institution")
        INTERNAL_HISTORY = "INTERNAL_HISTORY", _("Internal History")
        OTHER = "OTHER", _("Other")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    staff_id = models.ForeignKey(
        "hr_staff.HrStaffMaster", on_delete=models.PROTECT, related_name="work_experiences"
    )
    organization_name = models.CharField(max_length=200)
    department_name = models.CharField(max_length=200, blank=True, default="")
    position_title = models.CharField(max_length=120, blank=True, default="")
    industry_code = models.CharField(max_length=32, blank=True, default="")
    experience_type = models.CharField(
        max_length=24, choices=ExperienceType.choices, default=ExperienceType.UNIVERSITY
    )
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    is_internal = models.BooleanField(default=False)
    verification_status = models.CharField(
        max_length=16, choices=VerificationStatus.choices, default=VerificationStatus.UNVERIFIED
    )
    source = models.CharField(
        max_length=24, choices=SourceCategory.choices, default=SourceCategory.HR_ENTERED
    )
    version = models.BigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("HR Work Experience")
        verbose_name_plural = _("HR Work Experiences")
        constraints = [
            models.CheckConstraint(
                check=models.Q(end_date__isnull=True)
                | models.Q(start_date__isnull=True)
                | models.Q(end_date__gte=models.F("start_date")),
                name="chk_hr_work_end_gte_start",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant_id", "staff_id"]),
        ]

    def __str__(self):
        return f"{self.organization_name} {self.position_title}"
