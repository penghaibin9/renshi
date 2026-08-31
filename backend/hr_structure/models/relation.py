"""
hr_structure/models/relation.py

HrOrganizationRelation —— 党政组织与业务关系（总册 10 节）。

不变量（10.3）：
- source/target 同 tenant；
- 主树 parent 不得成环；
- 同组织同 dimension 同日期最多一个 primary parent；
- cross relation 允许多对多；
- relation 有生效期；历史不覆盖。
"""

from django.db import models
from django.utils.translation import gettext_lazy as _


class HrOrganizationRelation(models.Model):
    class RelationType(models.TextChoices):
        ADMIN_PARENT = "ADMIN_PARENT", _("Admin Parent")
        PARTY_PARENT = "PARTY_PARENT", _("Party Parent")
        TEACHING_PARENT = "TEACHING_PARENT", _("Teaching Parent")
        PARTY_COVERS = "PARTY_COVERS", _("Party Covers")
        ADMIN_MATCH = "ADMIN_MATCH", _("Admin Match")
        TEACHING_BELONGS_TO = "TEACHING_BELONGS_TO", _("Teaching Belongs To")
        BUSINESS_REPORTS_TO = "BUSINESS_REPORTS_TO", _("Business Reports To")
        BUSINESS_MANAGED_BY = "BUSINESS_MANAGED_BY", _("Business Managed By")
        SHARED_SERVICE_FOR = "SHARED_SERVICE_FOR", _("Shared Service For")
        TEMP_COORDINATION = "TEMP_COORDINATION", _("Temp Coordination")

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", _("Active")
        CLOSED = "CLOSED", _("Closed")

    tenant_id = models.BigIntegerField(db_index=True)
    source_org_id = models.ForeignKey(
        "HrOrganization", on_delete=models.PROTECT, related_name="relations_from"
    )
    target_org_id = models.ForeignKey(
        "HrOrganization", on_delete=models.PROTECT, related_name="relations_to"
    )
    relation_type = models.CharField(max_length=32, choices=RelationType.choices)
    validity_from = models.DateField()
    validity_to = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    change_case_id = models.CharField(max_length=64, blank=True, default="")
    metadata_json = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.CharField(max_length=128, blank=True, default="")

    class Meta:
        verbose_name = _("HR Organization Relation")
        verbose_name_plural = _("HR Organization Relations")
        indexes = [
            models.Index(fields=["tenant_id", "source_org_id", "relation_type"]),
            models.Index(fields=["tenant_id", "target_org_id", "relation_type"]),
        ]

    def __str__(self):
        return f"{self.source_org_id} -{self.relation_type}-> {self.target_org_id}"
