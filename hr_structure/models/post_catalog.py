"""
hr_structure/models/post_catalog.py

岗位目录（总册 12 节）：
- HrPostGradeScheme + HrPostGrade：岗位等级方案
- HrPostCatalog + HrPostCatalogVersion：岗位标准（stable + version）

原则：
- 岗位标准与岗位实例分离；
- 已被引用的 catalog 禁止破坏性改类别；重要语义变化创建新版本；
- 禁止删除已使用岗位目录。
"""

from django.db import models
from django.utils.translation import gettext_lazy as _


class HrPostGradeScheme(models.Model):
    tenant_id = models.BigIntegerField(db_index=True)
    code = models.CharField(max_length=64)
    name = models.CharField(max_length=200)
    category = models.CharField(max_length=64)
    validity_from = models.DateField()
    validity_to = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=16, default="ACTIVE")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("HR Post Grade Scheme")
        verbose_name_plural = _("HR Post Grade Schemes")
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "code"],
                name="uniq_hr_grade_scheme_tenant_code",
            ),
        ]

    def __str__(self):
        return f"{self.code} {self.name}"


class HrPostGrade(models.Model):
    scheme_id = models.ForeignKey(HrPostGradeScheme, on_delete=models.PROTECT, related_name="grades")
    code = models.CharField(max_length=64)
    name = models.CharField(max_length=200)
    rank_order = models.IntegerField(default=0)
    level_number = models.IntegerField(default=0)
    parent_band = models.CharField(max_length=64, blank=True, default="")
    is_entry_level = models.BooleanField(default=False)
    is_top_level = models.BooleanField(default=False)

    class Meta:
        verbose_name = _("HR Post Grade")
        verbose_name_plural = _("HR Post Grades")
        ordering = ["rank_order"]


class HrPostCatalog(models.Model):
    """岗位标准稳定身份。"""

    tenant_id = models.BigIntegerField(db_index=True)
    stable_code = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("HR Post Catalog")
        verbose_name_plural = _("HR Post Catalogs")
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "stable_code"],
                name="uniq_hr_post_catalog_tenant_code",
            ),
        ]


class HrPostCatalogVersion(models.Model):
    class Category(models.TextChoices):
        MANAGEMENT = "MANAGEMENT", _("Management")
        PROFESSIONAL_TECHNICAL = "PROFESSIONAL_TECHNICAL", _("Professional Technical")
        SKILLED_WORKER = "SKILLED_WORKER", _("Skilled Worker")
        SPECIAL = "SPECIAL", _("Special")

    class Subcategory(models.TextChoices):
        TEACHER = "TEACHER", _("Teacher")
        ENGINEERING_TECHNICAL = "ENGINEERING_TECHNICAL", _("Engineering Technical")
        LABORATORY = "LABORATORY", _("Laboratory")
        LIBRARY_ARCHIVES = "LIBRARY_ARCHIVES", _("Library Archives")
        ACCOUNTING_AUDIT = "ACCOUNTING_AUDIT", _("Accounting Audit")
        MEDICAL_HEALTH = "MEDICAL_HEALTH", _("Medical Health")
        EDITORIAL_PUBLICATION = "EDITORIAL_PUBLICATION", _("Editorial Publication")
        OTHER_PROFESSIONAL = "OTHER_PROFESSIONAL", _("Other Professional")

    class ControlMode(models.TextChoices):
        POSITION_CONTROL = "POSITION_CONTROL", _("Position Control")
        POOL_CONTROL = "POOL_CONTROL", _("Pool Control")

    class TimeType(models.TextChoices):
        FULL_TIME = "FULL_TIME", _("Full Time")
        PART_TIME = "PART_TIME", _("Part Time")
        BOTH = "BOTH", _("Both")

    class Status(models.TextChoices):
        DRAFT = "DRAFT", _("Draft")
        ACTIVE = "ACTIVE", _("Active")
        DISABLED = "DISABLED", _("Disabled")

    catalog_id = models.ForeignKey(HrPostCatalog, on_delete=models.PROTECT, related_name="versions")
    tenant_id = models.BigIntegerField(db_index=True)
    name = models.CharField(max_length=200)
    category = models.CharField(max_length=32, choices=Category.choices, default=Category.PROFESSIONAL_TECHNICAL)
    subcategory = models.CharField(max_length=32, choices=Subcategory.choices, blank=True, default="")
    grade_scheme_id = models.ForeignKey(HrPostGradeScheme, on_delete=models.PROTECT, null=True, blank=True)
    min_grade_id = models.ForeignKey(HrPostGrade, on_delete=models.PROTECT, null=True, blank=True, related_name="min_of")
    max_grade_id = models.ForeignKey(HrPostGrade, on_delete=models.PROTECT, null=True, blank=True, related_name="max_of")
    default_grade_id = models.ForeignKey(HrPostGrade, on_delete=models.PROTECT, null=True, blank=True, related_name="default_of")
    control_mode = models.CharField(max_length=16, choices=ControlMode.choices, default=ControlMode.POSITION_CONTROL)
    standard_fte = models.DecimalField(max_digits=5, decimal_places=2, default=1.00)
    time_type = models.CharField(max_length=16, choices=TimeType.choices, default=TimeType.FULL_TIME)
    worker_types_json = models.JSONField(default=list, blank=True)
    responsibilities_text = models.TextField(blank=True, default="")
    qualification_rule_json = models.JSONField(default=dict, blank=True)
    requires_professional_credential = models.BooleanField(default=False)
    is_special_post = models.BooleanField(default=False)
    validity_from = models.DateField()
    validity_to = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    version_no = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("HR Post Catalog Version")
        verbose_name_plural = _("HR Post Catalog Versions")

    def __str__(self):
        return f"{self.name} [{self.category}/{self.subcategory}]"
