"""
hr_structure/models/organization.py

HrOrganization + HrOrganizationVersion —— 稳定身份 + 生效期版本（总册 8 节）。

原则：
- 组织身份（stable_code）稳定，属性（名称/父级/类型）随版本变化。
- 同一 organization_id 的正式版本有效期不得重叠（INV-04）。
- stable_code tenant 内唯一、正式使用后不复用（INV-06）。
- 历史版本只读（INV-05 / INV-12）。
"""

from django.db import models
from django.utils.translation import gettext_lazy as _


class HrOrganization(models.Model):
    """稳定组织身份。"""

    class IdentityStatus(models.TextChoices):
        ACTIVE = "ACTIVE", _("Active")
        CLOSED = "CLOSED", _("Closed")

    class Dimension(models.TextChoices):
        ADMIN = "ADMIN", _("Administrative")
        PARTY = "PARTY", _("Party")
        TEACHING = "TEACHING", _("Teaching")
        BUSINESS = "BUSINESS", _("Business")

    tenant_id = models.BigIntegerField(db_index=True)
    stable_code = models.CharField(max_length=64)
    org_dimension = models.CharField(max_length=16, choices=Dimension.choices, default=Dimension.ADMIN)
    identity_status = models.CharField(max_length=16, choices=IdentityStatus.choices, default=IdentityStatus.ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.CharField(max_length=128, blank=True, default="")
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _("HR Organization")
        verbose_name_plural = _("HR Organizations")
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "stable_code"],
                name="uniq_hr_org_tenant_stable_code",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant_id", "org_dimension"]),
            models.Index(fields=["tenant_id", "identity_status"]),
        ]

    def __str__(self):
        return f"{self.stable_code} ({self.org_dimension})"


class HrOrganizationVersion(models.Model):
    """组织版本（effective-dated）。"""

    class OrgType(models.TextChoices):
        SCHOOL = "SCHOOL", _("School")
        CAMPUS = "CAMPUS", _("Campus")
        COLLEGE = "COLLEGE", _("College")
        DEPARTMENT = "DEPARTMENT", _("Department")
        OFFICE = "OFFICE", _("Office")
        DIVISION = "DIVISION", _("Division")
        SECTION = "SECTION", _("Section")
        TEACHING_RESEARCH_UNIT = "TEACHING_RESEARCH_UNIT", _("Teaching Research Unit")
        LAB_CENTER = "LAB_CENTER", _("Lab Center")
        RESEARCH_INSTITUTE = "RESEARCH_INSTITUTE", _("Research Institute")
        DIRECT_AFFILIATED_UNIT = "DIRECT_AFFILIATED_UNIT", _("Direct Affiliated Unit")
        PARTY_COMMITTEE = "PARTY_COMMITTEE", _("Party Committee")
        PARTY_GENERAL_BRANCH = "PARTY_GENERAL_BRANCH", _("Party General Branch")
        PARTY_BRANCH = "PARTY_BRANCH", _("Party Branch")
        VIRTUAL_ORG = "VIRTUAL_ORG", _("Virtual Org")
        TEMP_ORG = "TEMP_ORG", _("Temp Org")
        OTHER = "OTHER", _("Other")

    class Status(models.TextChoices):
        DRAFT = "DRAFT", _("Draft")
        APPROVED = "APPROVED", _("Approved")
        EFFECTIVE = "EFFECTIVE", _("Effective")
        SUPERSEDED = "SUPERSEDED", _("Superseded")
        REJECTED = "REJECTED", _("Rejected")
        CANCELLED = "CANCELLED", _("Cancelled")

    organization_id = models.ForeignKey(
        HrOrganization, on_delete=models.PROTECT, related_name="versions"
    )
    tenant_id = models.BigIntegerField(db_index=True)
    name = models.CharField(max_length=200)
    short_name = models.CharField(max_length=64, blank=True, default="")
    org_type = models.CharField(max_length=40, choices=OrgType.choices, default=OrgType.DEPARTMENT)
    parent_organization_id = models.ForeignKey(
        HrOrganization, on_delete=models.PROTECT, null=True, blank=True, related_name="child_versions"
    )
    validity_from = models.DateField()
    validity_to = models.DateField(null=True, blank=True)  # 半开区间 [from, to)，NULL=开放
    version_no = models.PositiveIntegerField(default=1)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    sort_order = models.IntegerField(default=0)
    location_code = models.CharField(max_length=64, blank=True, default="")
    change_case_id = models.CharField(max_length=64, blank=True, default="")
    source = models.CharField(max_length=32, blank=True, default="manual")
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.CharField(max_length=128, blank=True, default="")

    class Meta:
        verbose_name = _("HR Organization Version")
        verbose_name_plural = _("HR Organization Versions")
        indexes = [
            models.Index(fields=["tenant_id", "parent_organization_id", "status"]),
            models.Index(fields=["tenant_id", "status"]),
            models.Index(fields=["organization_id", "validity_from", "validity_to"]),
        ]

    def __str__(self):
        return f"{self.name} [{self.validity_from}~{self.validity_to or '∞'}]"
