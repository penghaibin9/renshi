"""
hr_structure/models/staffing.py

编制方案（总册 11 节）：
- HrStaffingPlan：方案（版本化、状态机）
- HrHeadcountQuotaLine：人员编制行
- HrPositionQuotaLine：岗位额度行
- HrLeadershipQuotaLine：领导职数行
- HrStructureRatioRule：结构比例规则（必须绑方案版本 INV-15）

原则：编制 ≠ 人数（INV-07）；实际人数不得自动回填编制。
"""

from django.db import models
from django.utils.translation import gettext_lazy as _


class HrStaffingPlan(models.Model):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", _("Draft")
        UNDER_REVIEW = "UNDER_REVIEW", _("Under Review")
        RETURNED = "RETURNED", _("Returned")
        REJECTED = "REJECTED", _("Rejected")
        APPROVED = "APPROVED", _("Approved")
        EFFECTIVE = "EFFECTIVE", _("Effective")
        SUPERSEDED = "SUPERSEDED", _("Superseded")
        CANCELLED = "CANCELLED", _("Cancelled")

    tenant_id = models.BigIntegerField(db_index=True)
    code = models.CharField(max_length=64)
    name = models.CharField(max_length=200)
    plan_year = models.IntegerField()
    validity_from = models.DateField()
    validity_to = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    version_no = models.PositiveIntegerField(default=1)
    basis_document_no = models.CharField(max_length=64, blank=True, default="")
    approval_instance_id = models.CharField(max_length=64, blank=True, default="")
    approved_at = models.DateTimeField(null=True, blank=True)
    locked_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.CharField(max_length=128, blank=True, default="")

    class Meta:
        verbose_name = _("HR Staffing Plan")
        verbose_name_plural = _("HR Staffing Plans")
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "code"],
                name="uniq_hr_plan_tenant_code",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant_id", "status", "validity_from"]),
        ]

    def __str__(self):
        return f"{self.code} {self.name} ({self.plan_year})"


class HrHeadcountQuotaLine(models.Model):
    class StaffingBasis(models.TextChoices):
        OFFICIAL_ESTABLISHMENT = "OFFICIAL_ESTABLISHMENT", _("Official Establishment")
        CONTROLLED_STAFFING = "CONTROLLED_STAFFING", _("Controlled Staffing")
        SCHOOL_FUNDED = "SCHOOL_FUNDED", _("School Funded")
        CONTRACT_EMPLOYMENT = "CONTRACT_EMPLOYMENT", _("Contract Employment")
        LABOR_DISPATCH = "LABOR_DISPATCH", _("Labor Dispatch")
        EXTERNAL_PART_TIME = "EXTERNAL_PART_TIME", _("External Part Time")
        OTHER = "OTHER", _("Other")

    class ControlMode(models.TextChoices):
        HARD = "HARD", _("Hard")
        SOFT = "SOFT", _("Soft")
        INFO_ONLY = "INFO_ONLY", _("Info Only")

    plan_id = models.ForeignKey(HrStaffingPlan, on_delete=models.PROTECT, related_name="headcount_lines")
    tenant_id = models.BigIntegerField(db_index=True)
    organization_id = models.ForeignKey("HrOrganization", on_delete=models.PROTECT)
    staffing_basis = models.CharField(max_length=32, choices=StaffingBasis.choices, default=StaffingBasis.OFFICIAL_ESTABLISHMENT)
    worker_category = models.CharField(max_length=64, blank=True, default="")
    authorized_headcount = models.PositiveIntegerField(default=0)
    reserve_headcount = models.PositiveIntegerField(default=0)
    control_mode = models.CharField(max_length=16, choices=ControlMode.choices, default=ControlMode.HARD)
    notes = models.TextField(blank=True, default="")
    version = models.PositiveIntegerField(default=1)

    class Meta:
        verbose_name = _("HR Headcount Quota Line")
        verbose_name_plural = _("HR Headcount Quota Lines")
        indexes = [
            models.Index(fields=["plan_id", "organization_id", "staffing_basis"]),
        ]


class HrPositionQuotaLine(models.Model):
    plan_id = models.ForeignKey(HrStaffingPlan, on_delete=models.PROTECT, related_name="position_lines")
    tenant_id = models.BigIntegerField(db_index=True)
    organization_id = models.ForeignKey("HrOrganization", on_delete=models.PROTECT)
    post_category = models.CharField(max_length=64)
    post_grade = models.CharField(max_length=64, blank=True, default="")
    post_catalog_id = models.ForeignKey("HrPostCatalog", on_delete=models.PROTECT, null=True, blank=True)
    authorized_positions = models.PositiveIntegerField(default=0)
    authorized_fte = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    control_mode = models.CharField(max_length=16, default="HARD")

    class Meta:
        verbose_name = _("HR Position Quota Line")
        verbose_name_plural = _("HR Position Quota Lines")


class HrLeadershipQuotaLine(models.Model):
    plan_id = models.ForeignKey(HrStaffingPlan, on_delete=models.PROTECT, related_name="leadership_lines")
    tenant_id = models.BigIntegerField(db_index=True)
    organization_id = models.ForeignKey("HrOrganization", on_delete=models.PROTECT)
    leadership_level = models.CharField(max_length=64)
    quota_count = models.PositiveIntegerField(default=0)
    control_mode = models.CharField(max_length=16, default="HARD")

    class Meta:
        verbose_name = _("HR Leadership Quota Line")
        verbose_name_plural = _("HR Leadership Quota Lines")


class HrStructureRatioRule(models.Model):
    class Severity(models.TextChoices):
        BLOCKER = "BLOCKER", _("Blocker")
        WARNING = "WARNING", _("Warning")
        INFO = "INFO", _("Info")

    plan_id = models.ForeignKey(HrStaffingPlan, on_delete=models.PROTECT, related_name="ratio_rules")
    tenant_id = models.BigIntegerField(db_index=True)
    scope_type = models.CharField(max_length=32, default="SCHOOL")
    scope_id = models.BigIntegerField(null=True, blank=True)
    numerator_dimension = models.CharField(max_length=64)
    numerator_values = models.JSONField(default=list, blank=True)
    denominator_dimension = models.CharField(max_length=64)
    denominator_values = models.JSONField(default=list, blank=True)
    operator = models.CharField(max_length=8, default="<=")
    threshold = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    severity = models.CharField(max_length=16, choices=Severity.choices, default=Severity.WARNING)
    control_mode = models.CharField(max_length=16, default="SOFT")
    source_policy = models.CharField(max_length=64, blank=True, default="")

    class Meta:
        verbose_name = _("HR Structure Ratio Rule")
        verbose_name_plural = _("HR Structure Ratio Rules")
