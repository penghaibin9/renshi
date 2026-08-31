"""
hr_structure/models/change_case.py

组织岗位变更（总册 14 节）：
- HrStructureChangeCase：重组 case
- HrStructureChangeItem：原子变更项

原则：
- 不直接 UPDATE 下游（INV-10）；
- 已批准 future version 不可直接修改（INV-13）；
- 正式实体不物理删除。
"""

from django.db import models
from django.utils.translation import gettext_lazy as _


class HrStructureChangeCase(models.Model):
    class ChangeType(models.TextChoices):
        CREATE_ORG = "CREATE_ORG", _("Create Org")
        RENAME_ORG = "RENAME_ORG", _("Rename Org")
        CHANGE_ORG_TYPE = "CHANGE_ORG_TYPE", _("Change Org Type")
        REPARENT_ORG = "REPARENT_ORG", _("Reparent Org")
        MERGE_ORGS = "MERGE_ORGS", _("Merge Orgs")
        SPLIT_ORG = "SPLIT_ORG", _("Split Org")
        DEACTIVATE_ORG = "DEACTIVATE_ORG", _("Deactivate Org")
        REACTIVATE_ORG = "REACTIVATE_ORG", _("Reactivate Org")
        CREATE_RELATION = "CREATE_RELATION", _("Create Relation")
        CHANGE_RELATION = "CHANGE_RELATION", _("Change Relation")
        MOVE_POSITION = "MOVE_POSITION", _("Move Position")
        CREATE_POSITION = "CREATE_POSITION", _("Create Position")
        CHANGE_POSITION = "CHANGE_POSITION", _("Change Position")
        CLOSE_POSITION = "CLOSE_POSITION", _("Close Position")
        ADJUST_STAFFING_QUOTA = "ADJUST_STAFFING_QUOTA", _("Adjust Staffing Quota")
        ADJUST_POSITION_QUOTA = "ADJUST_POSITION_QUOTA", _("Adjust Position Quota")

    class Status(models.TextChoices):
        DRAFT = "DRAFT", _("Draft")
        SUBMITTED = "SUBMITTED", _("Submitted")
        UNDER_REVIEW = "UNDER_REVIEW", _("Under Review")
        RETURNED = "RETURNED", _("Returned")
        REJECTED = "REJECTED", _("Rejected")
        APPROVED = "APPROVED", _("Approved")
        SCHEDULED = "SCHEDULED", _("Scheduled")
        EFFECTIVE = "EFFECTIVE", _("Effective")
        CANCELLED = "CANCELLED", _("Cancelled")
        FAILED_EFFECT = "FAILED_EFFECT", _("Failed Effect")

    tenant_id = models.BigIntegerField(db_index=True)
    case_no = models.CharField(max_length=64)
    change_type = models.CharField(max_length=32, choices=ChangeType.choices)
    title = models.CharField(max_length=200)
    reason = models.TextField(blank=True, default="")
    requested_effective_date = models.DateField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    initiator_id = models.CharField(max_length=128, blank=True, default="")
    approval_instance_id = models.CharField(max_length=64, blank=True, default="")
    impact_snapshot_json = models.JSONField(default=dict, blank=True)
    precondition_hash = models.CharField(max_length=64, blank=True, default="")
    approved_at = models.DateTimeField(null=True, blank=True)
    executed_at = models.DateTimeField(null=True, blank=True)
    execution_result_json = models.JSONField(default=dict, blank=True)
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.CharField(max_length=128, blank=True, default="")

    class Meta:
        verbose_name = _("HR Structure Change Case")
        verbose_name_plural = _("HR Structure Change Cases")
        indexes = [
            models.Index(fields=["tenant_id", "status", "requested_effective_date"]),
        ]

    def __str__(self):
        return f"{self.case_no} {self.title}"


class HrStructureChangeItem(models.Model):
    case_id = models.ForeignKey(HrStructureChangeCase, on_delete=models.PROTECT, related_name="items")
    sequence = models.PositiveIntegerField(default=0)
    entity_type = models.CharField(max_length=64)
    entity_id = models.CharField(max_length=64)
    action_type = models.CharField(max_length=64)
    before_snapshot = models.JSONField(default=dict, blank=True)
    after_payload = models.JSONField(default=dict, blank=True)
    validation_status = models.CharField(max_length=16, default="PENDING")
    execution_status = models.CharField(max_length=16, default="PENDING")

    class Meta:
        verbose_name = _("HR Structure Change Item")
        verbose_name_plural = _("HR Structure Change Items")
        ordering = ["case_id", "sequence"]
