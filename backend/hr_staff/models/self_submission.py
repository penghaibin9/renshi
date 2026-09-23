"""HR03 owns supplementary evidence; HR17 never owns its approval state."""
import uuid
from django.db import models

class HrMaterialSubmission(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    request = models.ForeignKey("hr_staff.HrMaterialRequest", on_delete=models.PROTECT, related_name="submissions")
    material_version = models.ForeignKey("hr_staff.HrStaffMaterialVersion", on_delete=models.PROTECT, related_name="self_submissions")
    revision = models.PositiveIntegerField()
    status = models.CharField(max_length=16, default="SUBMITTED")
    submitted_by = models.BigIntegerField()
    evidence_hash = models.CharField(max_length=64)
    review_reason = models.CharField(max_length=512, blank=True, default="")
    reviewed_by = models.BigIntegerField(null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "hr03_material_submission"
        constraints = [models.UniqueConstraint(fields=("tenant_id", "request", "revision"), name="uq_hr03_material_response_rev")]
        indexes = [models.Index(fields=("tenant_id", "status", "created_at"), name="idx_hr03_material_review")]

    def delete(self, *args, **kwargs):
        raise ValueError("MATERIAL_SUBMISSION_DELETE_FORBIDDEN")
