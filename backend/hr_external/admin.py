"""
hr_external/admin.py —— HR08 Django Admin（00 §141）。

正式 Authority 默认受限/只读/高权限；不能成为绕工作流后门。
"""

from django.contrib import admin

from hr_external.models import (
    HrExternalAccessGrant,
    HrExternalAcademicIdentity,
    HrExternalAcademicProvisioningRequest,
    HrExternalAuditEvent,
    HrExternalAuthorityConfig,
    HrExternalCategory,
    HrExternalConflictDeclaration,
    HrExternalContribution,
    HrExternalEngagement,
    HrExternalEngagementAssignment,
    HrExternalEthicsReview,
    HrExternalExitCase,
    HrExternalFileTicket,
    HrExternalHiringCase,
    HrExternalImportJob,
    HrExternalImportRow,
    HrExternalIndustryProfile,
    HrExternalLifecycleEvent,
    HrExternalMaterial,
    HrExternalPortalToken,
    HrExternalProjectionState,
    HrExternalProvisioningRequest,
    HrExternalRenewalReview,
    HrExternalServiceTask,
    HrExternalSettlementBasis,
    HrExternalTaskEvidence,
    HrExternalTaskPlan,
    HrExternalTeacherProfile,
    HrExternalWorkloadRecord,
    HrExternalWorkspace,
    HrSensitiveExternalAccessLog,
)


class ReadOnlyAdmin(admin.ModelAdmin):
    """只读 Admin 基类：禁止 add/change/delete，防绕工作流后门。"""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(HrExternalCategory)
class HrExternalCategoryAdmin(ReadOnlyAdmin):
    list_display = ("tenant_id", "code", "name", "is_active", "version")
    list_filter = ("is_active", "is_system_builtin")
    search_fields = ("code", "name")
    readonly_fields = ("id", "tenant_id", "version", "created_at", "updated_at")


@admin.register(HrExternalTeacherProfile)
class HrExternalTeacherProfileAdmin(ReadOnlyAdmin):
    list_display = (
        "tenant_id",
        "external_teacher_no",
        "person_id",
        "candidate_pool_status",
        "identity_verification_status",
    )
    list_filter = ("candidate_pool_status", "ethics_status")
    search_fields = ("external_teacher_no",)
    readonly_fields = ("id", "tenant_id", "person_id", "version", "created_at", "updated_at")


@admin.register(HrExternalEngagement)
class HrExternalEngagementAdmin(ReadOnlyAdmin):
    list_display = (
        "tenant_id",
        "engagement_no",
        "person_id",
        "status",
        "start_at",
        "end_at",
        "agreement_status",
    )
    list_filter = ("status", "source_type")
    search_fields = ("engagement_no",)
    readonly_fields = ("id", "tenant_id", "version", "created_at", "updated_at")


@admin.register(HrExternalEngagementAssignment)
class HrExternalEngagementAssignmentAdmin(ReadOnlyAdmin):
    list_display = ("tenant_id", "engagement_id", "assignment_type", "is_primary", "status")
    list_filter = ("assignment_type", "status")
    readonly_fields = ("id", "tenant_id", "version", "created_at", "updated_at")


@admin.register(HrExternalHiringCase)
class HrExternalHiringCaseAdmin(ReadOnlyAdmin):
    list_display = ("tenant_id", "case_no", "request_org_id", "status")
    list_filter = ("status",)
    search_fields = ("case_no",)
    readonly_fields = ("id", "tenant_id", "version", "created_at", "updated_at")


@admin.register(HrExternalEthicsReview)
class HrExternalEthicsReviewAdmin(ReadOnlyAdmin):
    list_display = ("tenant_id", "person_id", "status", "reviewer", "reviewed_at")
    list_filter = ("status",)
    readonly_fields = ("id", "tenant_id", "version", "created_at", "updated_at")


@admin.register(HrExternalConflictDeclaration)
class HrExternalConflictDeclarationAdmin(ReadOnlyAdmin):
    list_display = ("tenant_id", "person_id", "conflict_type", "declared", "status")
    list_filter = ("status",)
    readonly_fields = ("id", "tenant_id", "version", "created_at", "updated_at")


@admin.register(HrExternalAccessGrant)
class HrExternalAccessGrantAdmin(ReadOnlyAdmin):
    list_display = ("tenant_id", "engagement_id", "target_system", "role_code", "status")
    list_filter = ("status", "target_system")
    readonly_fields = ("id", "tenant_id", "version", "created_at", "updated_at")


@admin.register(HrExternalProvisioningRequest)
class HrExternalProvisioningRequestAdmin(ReadOnlyAdmin):
    list_display = ("tenant_id", "engagement_id", "target_system", "operation", "status")
    list_filter = ("status", "operation", "target_system")
    readonly_fields = ("id", "tenant_id", "version", "created_at", "updated_at")


@admin.register(HrExternalLifecycleEvent)
class HrExternalLifecycleEventAdmin(ReadOnlyAdmin):
    list_display = ("tenant_id", "event_type", "event_version", "status", "occurred_at")
    list_filter = ("event_type", "status")
    readonly_fields = ("id", "tenant_id", "event_id", "occurred_at")


@admin.register(HrExternalAuditEvent)
class HrExternalAuditEventAdmin(ReadOnlyAdmin):
    list_display = ("tenant_id", "action", "business_type", "occurred_at")
    list_filter = ("action",)
    readonly_fields = ("id", "tenant_id", "occurred_at")


@admin.register(HrExternalImportJob)
class HrExternalImportJobAdmin(ReadOnlyAdmin):
    list_display = ("tenant_id", "job_type", "status", "total_rows", "success_count", "failed_count")
    list_filter = ("job_type", "status")
    readonly_fields = ("id", "tenant_id", "created_at", "updated_at")


@admin.register(HrExternalImportRow)
class HrExternalImportRowAdmin(ReadOnlyAdmin):
    list_display = ("tenant_id", "job_id", "row_no", "status")
    list_filter = ("status",)
    readonly_fields = ("id", "tenant_id", "created_at")


@admin.register(HrExternalIndustryProfile)
class HrExternalIndustryProfileAdmin(ReadOnlyAdmin):
    list_display = ("tenant_id", "profile_id", "current_employer", "industry_experience_years")
    readonly_fields = ("id", "tenant_id", "version", "created_at", "updated_at")


@admin.register(HrExternalContribution)
class HrExternalContributionAdmin(ReadOnlyAdmin):
    list_display = ("tenant_id", "engagement_id", "contribution_type", "title", "verification_status", "status")
    list_filter = ("contribution_type", "verification_status", "status")
    readonly_fields = ("id", "tenant_id", "version", "created_at", "updated_at")


@admin.register(HrExternalWorkspace)
class HrExternalWorkspaceAdmin(ReadOnlyAdmin):
    list_display = ("tenant_id", "name", "workspace_type", "organization_id", "status")
    list_filter = ("workspace_type", "status")
    readonly_fields = ("id", "tenant_id", "version", "created_at", "updated_at")


@admin.register(HrExternalAcademicIdentity)
class HrExternalAcademicIdentityAdmin(ReadOnlyAdmin):
    list_display = ("tenant_id", "engagement_id", "academic_teacher_id", "status", "valid_from", "valid_to")
    list_filter = ("status",)
    readonly_fields = ("id", "tenant_id", "version", "created_at", "updated_at")


@admin.register(HrExternalAcademicProvisioningRequest)
class HrExternalAcademicProvisioningRequestAdmin(ReadOnlyAdmin):
    list_display = ("tenant_id", "academic_identity_id", "operation", "status", "retry_count")
    list_filter = ("operation", "status")
    readonly_fields = ("id", "tenant_id", "version", "created_at", "updated_at")


@admin.register(HrExternalServiceTask)
class HrExternalServiceTaskAdmin(ReadOnlyAdmin):
    list_display = ("tenant_id", "engagement_id", "task_type", "title", "status", "acceptance")
    list_filter = ("status", "task_type")
    readonly_fields = ("id", "tenant_id", "version", "created_at", "updated_at")


@admin.register(HrExternalTaskEvidence)
class HrExternalTaskEvidenceAdmin(ReadOnlyAdmin):
    list_display = ("tenant_id", "task_id", "evidence_type", "status")
    readonly_fields = ("id", "tenant_id", "created_at")


@admin.register(HrExternalWorkloadRecord)
class HrExternalWorkloadRecordAdmin(ReadOnlyAdmin):
    list_display = ("tenant_id", "engagement_id", "quantity", "unit", "verification_status", "settlement_status")
    list_filter = ("verification_status", "settlement_status", "source")
    readonly_fields = ("id", "tenant_id", "version", "created_at", "updated_at")


@admin.register(HrExternalSettlementBasis)
class HrExternalSettlementBasisAdmin(ReadOnlyAdmin):
    list_display = ("tenant_id", "engagement_id", "period", "verified_workload", "status")
    list_filter = ("status",)
    readonly_fields = ("id", "tenant_id", "version", "created_at", "updated_at")


@admin.register(HrExternalRenewalReview)
class HrExternalRenewalReviewAdmin(ReadOnlyAdmin):
    list_display = ("tenant_id", "engagement_id", "review_due_at", "status", "decision")
    list_filter = ("status",)
    readonly_fields = ("id", "tenant_id", "version", "created_at", "updated_at")


@admin.register(HrExternalExitCase)
class HrExternalExitCaseAdmin(ReadOnlyAdmin):
    list_display = ("tenant_id", "engagement_id", "exit_reason", "status", "planned_end_at", "actual_end_at")
    list_filter = ("status", "exit_reason")
    readonly_fields = ("id", "tenant_id", "version", "created_at", "updated_at")


@admin.register(HrExternalProjectionState)
class HrExternalProjectionStateAdmin(ReadOnlyAdmin):
    list_display = ("tenant_id", "external_profile_id", "worker_kind", "status", "legacy_employee_id", "mismatch_count")
    list_filter = ("status", "worker_kind")
    readonly_fields = ("id", "tenant_id", "created_at", "updated_at")


@admin.register(HrExternalAuthorityConfig)
class HrExternalAuthorityConfigAdmin(ReadOnlyAdmin):
    list_display = ("tenant_id", "authority_mode", "cutover_at", "legacy_write_disabled")
    list_filter = ("authority_mode",)
    readonly_fields = ("id", "tenant_id", "created_at", "updated_at")


@admin.register(HrExternalMaterial)
class HrExternalMaterialAdmin(ReadOnlyAdmin):
    list_display = ("tenant_id", "external_profile_id", "category", "title", "sensitivity_level", "version_no", "status")
    list_filter = ("category", "status", "sensitivity_level")
    readonly_fields = ("id", "tenant_id", "sha256", "created_at", "updated_at")


@admin.register(HrExternalFileTicket)
class HrExternalFileTicketAdmin(ReadOnlyAdmin):
    list_display = ("tenant_id", "material_id", "actor_user_id", "used_count", "max_uses", "expires_at", "revoked")
    list_filter = ("revoked",)
    readonly_fields = ("id", "tenant_id", "token_hash", "created_at", "used_at")


@admin.register(HrExternalPortalToken)
class HrExternalPortalTokenAdmin(ReadOnlyAdmin):
    list_display = ("tenant_id", "external_profile_id", "status", "expires_at")
    list_filter = ("status",)
    readonly_fields = ("id", "tenant_id", "token_hash", "issued_at", "revoked_at")


@admin.register(HrExternalTaskPlan)
class HrExternalTaskPlanAdmin(ReadOnlyAdmin):
    list_display = ("tenant_id", "engagement_id", "plan_version", "status", "period_start", "period_end")
    readonly_fields = ("id", "tenant_id", "created_at", "updated_at")


@admin.register(HrSensitiveExternalAccessLog)
class HrSensitiveExternalAccessLogAdmin(ReadOnlyAdmin):
    list_display = ("tenant_id", "external_profile_id", "field_code", "action", "revealed_at")
    list_filter = ("action",)
    readonly_fields = ("id", "tenant_id", "revealed_at")
