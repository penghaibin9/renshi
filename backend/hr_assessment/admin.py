"""HR12 Assessment — Django Admin 注册（全部 45 个 Authority 模型）。"""

from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from hr_assessment.models.policy import (
    HrAssessmentPolicyPack,
    HrAssessmentPolicyVersion,
    HrRatingScaleVersion,
    HrIndicatorDefinition,
    HrIndicatorVersion,
    HrIndicatorSetVersion,
    HrAssessmentWorkflowVersion,
    HrAssessmentClassificationProfileVersion,
    HrEvidenceRequirement,
    HrGateRule,
    HrGateRuleVersion,
    HrResultRuleVersion,
    HrExcellentQuotaPolicy,
)
from hr_assessment.models.cycle import (
    HrAssessmentCycle,
    HrCycleSnapshot,
    HrAssessmentPopulationSnapshot,
)
from hr_assessment.models.goal import (
    HrAssessmentGoalPlan,
    HrAssessmentGoal,
    HrGoalVersion,
    HrGoalAssignment,
    HrRoutineAssessmentEntry,
)
from hr_assessment.models.evidence import (
    HrAssessmentEvidenceRef,
    HrMetricSnapshot,
    HrSelfAssessment,
    HrReviewerAssignment,
    HrReviewerEvaluation,
    HrQuestionnaireVersion,
    HrMultiRaterSession,
)
from hr_assessment.models.case import (
    HrSubjectSnapshot,
    HrAssessmentCase,
    HrAnnualAssessmentCase,
    HrTermAssessmentCase,
    HrSpecialAssessmentCase,
    HrEthicsAssessmentCase,
    HrAssessmentPublicityCase,
)
from hr_assessment.models.result import (
    HrAssessmentDecisionSession,
    HrAssessmentDocument,
    HrCalibrationSession,
    HrFinalAssessmentResult,
    HrResultNotice,
    HrAssessmentObjection,
    HrResultRevision,
    HrAssessmentArchivePackage,
    HrResultApplicationLedger,
)
from hr_assessment.models.legacy import HrAssessmentCutoverEvent


@admin.register(HrAssessmentPolicyPack)
class PolicyPackAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "assessment_domain", "tenant_id")
    list_filter = ("assessment_domain",)
    search_fields = ("code", "name")


@admin.register(HrAssessmentPolicyVersion)
class PolicyVersionAdmin(admin.ModelAdmin):
    list_display = ("__str__", "version_no", "status", "effective_from")
    list_filter = ("status",)
    readonly_fields = ("content_hash",)


@admin.register(HrRatingScaleVersion)
class RatingScaleAdmin(admin.ModelAdmin):
    list_display = ("__str__", "scale_type", "min_value", "max_value", "version_no", "status")


@admin.register(HrIndicatorDefinition)
class IndicatorDefAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "dimension", "is_active", "tenant_id")
    list_filter = ("dimension", "is_active")
    search_fields = ("code", "name")


@admin.register(HrIndicatorVersion)
class IndicatorVersionAdmin(admin.ModelAdmin):
    list_display = ("__str__", "dimension", "value_type", "source_provider", "status")
    list_filter = ("status", "source_provider")


@admin.register(HrIndicatorSetVersion)
class IndicatorSetAdmin(admin.ModelAdmin):
    list_display = ("name", "total_weight", "version_no", "status")


@admin.register(HrAssessmentWorkflowVersion)
class WorkflowAdmin(admin.ModelAdmin):
    list_display = ("name", "version_no", "status")


@admin.register(HrAssessmentClassificationProfileVersion)
class ClassificationProfileAdmin(admin.ModelAdmin):
    list_display = ("name", "job_family", "position_category", "version_no")
    list_filter = ("job_family",)


@admin.register(HrEvidenceRequirement)
class EvidenceReqAdmin(admin.ModelAdmin):
    list_display = ("indicator_version", "min_trust_level", "fallback_mode")
    list_filter = ("min_trust_level", "fallback_mode")


@admin.register(HrGateRule)
class GateRuleAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "gate_type")


@admin.register(HrGateRuleVersion)
class GateRuleVersionAdmin(admin.ModelAdmin):
    list_display = ("__str__", "effect_code", "version_no", "status")


@admin.register(HrResultRuleVersion)
class ResultRuleAdmin(admin.ModelAdmin):
    list_display = ("name", "version_no", "status")


@admin.register(HrExcellentQuotaPolicy)
class QuotaPolicyAdmin(admin.ModelAdmin):
    list_display = ("name", "max_excellent_ratio", "over_quota_action", "effective_from")
    list_filter = ("over_quota_action",)


@admin.register(HrAssessmentCycle)
class CycleAdmin(admin.ModelAdmin):
    list_display = ("cycle_no", "name", "assessment_type", "lifecycle_status", "tenant_id")
    list_filter = ("assessment_type", "lifecycle_status")
    search_fields = ("cycle_no", "name")


@admin.register(HrCycleSnapshot)
class CycleSnapshotAdmin(admin.ModelAdmin):
    list_display = ("cycle", "frozen_at")
    readonly_fields = ("frozen_at",)


@admin.register(HrAssessmentPopulationSnapshot)
class PopulationSnapshotAdmin(admin.ModelAdmin):
    list_display = ("staff_id", "org_id", "included", "snapshot_at")
    list_filter = ("included", "cycle")


@admin.register(HrAssessmentGoalPlan)
class GoalPlanAdmin(admin.ModelAdmin):
    list_display = ("name", "goal_type", "status")


@admin.register(HrAssessmentGoal)
class GoalAdmin(admin.ModelAdmin):
    list_display = ("goal_code", "owner_type", "status", "source_type")
    list_filter = ("status", "owner_type")
    search_fields = ("goal_code",)


@admin.register(HrGoalVersion)
class GoalVersionAdmin(admin.ModelAdmin):
    list_display = ("__str__", "title", "version_no", "status")
    list_filter = ("status",)


@admin.register(HrGoalAssignment)
class GoalAssignmentAdmin(admin.ModelAdmin):
    list_display = ("goal", "staff_id", "assignment_type")
    list_filter = ("assignment_type",)


@admin.register(HrRoutineAssessmentEntry)
class RoutineEntryAdmin(admin.ModelAdmin):
    list_display = ("staff_id", "category", "status", "revision")


@admin.register(HrAssessmentEvidenceRef)
class EvidenceRefAdmin(admin.ModelAdmin):
    list_display = ("case_id", "provider_type", "trust_level", "status")
    list_filter = ("provider_type", "trust_level", "status")


@admin.register(HrMetricSnapshot)
class MetricSnapshotAdmin(admin.ModelAdmin):
    list_display = ("case_id", "metric_code", "value", "provider", "status")
    list_filter = ("provider", "status")


@admin.register(HrSelfAssessment)
class SelfAssessmentAdmin(admin.ModelAdmin):
    list_display = ("case_id", "submitted_at", "revision")
    readonly_fields = ("submitted_at",)


@admin.register(HrReviewerAssignment)
class ReviewerAssignmentAdmin(admin.ModelAdmin):
    list_display = ("case_id", "reviewer_role", "reviewer_staff_id", "conflict_status", "status")
    list_filter = ("reviewer_role", "conflict_status")


@admin.register(HrReviewerEvaluation)
class ReviewerEvaluationAdmin(admin.ModelAdmin):
    list_display = ("assignment", "recommendation", "submitted_at", "revision_no")
    readonly_fields = ("submitted_at",)

    def get_readonly_fields(self, request, obj=None):
        if obj is not None and obj.submitted_at is not None:
            return tuple(field.name for field in obj._meta.concrete_fields)
        return super().get_readonly_fields(request, obj)

    def has_delete_permission(self, request, obj=None):
        if obj is not None and obj.submitted_at is not None:
            return False
        return super().has_delete_permission(request, obj)


@admin.register(HrQuestionnaireVersion)
class QuestionnaireAdmin(admin.ModelAdmin):
    list_display = ("name", "version_no", "status")


@admin.register(HrMultiRaterSession)
class MultiRaterSessionAdmin(admin.ModelAdmin):
    list_display = ("session_name", "case_id", "anonymity_strategy", "session_status")
    list_filter = ("anonymity_strategy", "session_status")


@admin.register(HrSubjectSnapshot)
class SubjectSnapshotAdmin(admin.ModelAdmin):
    list_display = ("staff_id", "display_name", "snapshot_at")


@admin.register(HrAssessmentCase)
class AssessmentCaseAdmin(admin.ModelAdmin):
    list_display = ("assessment_type", "staff_id", "status", "cycle")
    list_filter = ("assessment_type", "status")


@admin.register(HrAnnualAssessmentCase)
class AnnualCaseAdmin(admin.ModelAdmin):
    list_display = ("__str__", "business_year", "status")


@admin.register(HrTermAssessmentCase)
class TermCaseAdmin(admin.ModelAdmin):
    list_display = ("__str__", "term_start", "term_end", "status")


@admin.register(HrSpecialAssessmentCase)
class SpecialCaseAdmin(admin.ModelAdmin):
    list_display = ("title", "special_type", "status")


@admin.register(HrEthicsAssessmentCase)
class EthicsCaseAdmin(admin.ModelAdmin):
    list_display = ("__str__", "gate_status", "gate_reason_code")
    list_filter = ("gate_status",)


@admin.register(HrAssessmentPublicityCase)
class PublicityCaseAdmin(admin.ModelAdmin):
    list_display = ("__str__", "start_at", "end_at", "status")
    list_filter = ("status",)


@admin.register(HrCalibrationSession)
class CalibrationSessionAdmin(admin.ModelAdmin):
    list_display = ("__str__", "session_status", "opened_at", "closed_at")
    list_filter = ("session_status",)


@admin.register(HrAssessmentDecisionSession)
class DecisionSessionAdmin(admin.ModelAdmin):
    list_display = ("id", "cycle_id", "meeting_at", "status", "confidentiality")
    list_filter = ("status", "confidentiality")
    readonly_fields = ("minutes_document_ref",)

    def get_readonly_fields(self, request, obj=None):
        if obj is not None and obj.status == "COMPLETED":
            return tuple(field.name for field in obj._meta.concrete_fields)
        return super().get_readonly_fields(request, obj)

    def has_delete_permission(self, request, obj=None):
        if obj is not None and obj.status == "COMPLETED":
            return False
        return super().has_delete_permission(request, obj)


@admin.register(HrAssessmentDocument)
class AssessmentDocumentAdmin(admin.ModelAdmin):
    list_display = ("original_filename", "document_type", "related_object_id", "size_bytes", "status", "sealed_at")
    list_filter = ("document_type", "status")
    readonly_fields = (
        "tenant_id", "document_type", "related_object_type", "related_object_id",
        "storage_key", "original_filename", "content_type", "size_bytes", "sha256",
        "uploaded_by", "sealed_at", "status", "created_at", "updated_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(HrFinalAssessmentResult)
class FinalResultAdmin(admin.ModelAdmin):
    list_display = ("case_id", "assessment_type", "grade_code", "result_version_no", "status", "finalized_at")
    list_filter = ("assessment_type", "grade_code", "status")
    readonly_fields = ("finalized_at", "content_hash")
    search_fields = ("case_id",)


@admin.register(HrResultNotice)
class NoticeAdmin(admin.ModelAdmin):
    list_display = ("notice_no", "delivery_channel", "delivery_status")
    list_filter = ("delivery_status",)


@admin.register(HrAssessmentObjection)
class ObjectionAdmin(admin.ModelAdmin):
    list_display = ("__str__", "status", "submitted_at", "resolved_at")
    list_filter = ("status",)


@admin.register(HrResultRevision)
class RevisionAdmin(admin.ModelAdmin):
    list_display = ("__str__", "revision_type", "previous_version", "new_version")
    list_filter = ("revision_type",)


@admin.register(HrAssessmentArchivePackage)
class ArchivePackageAdmin(admin.ModelAdmin):
    list_display = ("archive_package_id", "archive_status", "archived_at")
    list_filter = ("archive_status",)


@admin.register(HrResultApplicationLedger)
class ApplicationLedgerAdmin(admin.ModelAdmin):
    list_display = ("consumer_domain", "purpose", "result_version", "consumer_status")
    list_filter = ("consumer_domain",)


@admin.register(HrAssessmentCutoverEvent)
class AssessmentCutoverEventAdmin(admin.ModelAdmin):
    list_display = (
        "tenant_id",
        "phase",
        "authority_mode",
        "operator",
        "occurred_at",
    )
    list_filter = ("tenant_id", "phase", "authority_mode")
    readonly_fields = (
        "tenant_id",
        "phase",
        "previous_phase",
        "authority_mode",
        "operator",
        "reason",
        "verification_report_id",
        "source_snapshot_hash",
        "occurred_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
