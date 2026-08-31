"""
hr_onboarding/admin.py

正式 Authority 默认受限/只读/高权限（00 §141）：
不能成为绕工作流后门。只读展示，不开放 CRUD 走 workflow 之外的写路径。
"""

from django.contrib import admin

from hr_onboarding.models import (
    HrActivationAttempt,
    HrOnboardingActivationSnapshot,
    HrOnboardingAuditEvent,
    HrOnboardingAuthorityMode,
    HrOnboardingCase,
    HrOnboardingDataConflict,
    HrOnboardingMaterial,
    HrOnboardingMaterialRequirement,
    HrOnboardingOutboxEvent,
    HrOnboardingStageTransition,
    HrOnboardingTaskDefinition,
    HrOnboardingTaskInstance,
    HrOnboardingTemplate,
    HrOnboardingTemplateVersion,
    HrPrehirePortalAccess,
    HrPrehireProfile,
    HrProbationCase,
    HrProbationExtension,
    HrProvisioningRequest,
    HrReportCheckin,
    HrReportDelay,
)


class ReadOnlyAdmin(admin.ModelAdmin):
    """只读基类：禁止新增/删除，修改必须走正式 workflow。"""

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        # 只读展示（修改仍走服务层/管理命令）
        return False


@admin.register(HrOnboardingCase)
class HrOnboardingCaseAdmin(ReadOnlyAdmin):
    list_display = ("case_no", "tenant_id", "source_type", "source_id", "status", "activation_status", "expected_report_date")
    list_filter = ("tenant_id", "status", "source_type")
    search_fields = ("case_no", "source_id", "hr04_proposed_hire_id")


@admin.register(HrOnboardingTemplate)
class HrOnboardingTemplateAdmin(ReadOnlyAdmin):
    list_display = ("code", "name", "tenant_id", "status")
    list_filter = ("tenant_id", "status")


@admin.register(HrOnboardingAuthorityMode)
class HrOnboardingAuthorityModeAdmin(ReadOnlyAdmin):
    list_display = ("tenant_id", "mode", "switched_by", "switched_at")
    list_filter = ("mode",)


@admin.register(HrOnboardingOutboxEvent)
class HrOnboardingOutboxEventAdmin(ReadOnlyAdmin):
    list_display = (
        "event_type",
        "tenant_id",
        "aggregate_id",
        "status",
        "attempts",
        "next_attempt_at",
        "lease_expires_at",
        "external_ref",
        "occurred_at",
    )
    list_filter = ("status", "event_type")


@admin.register(HrOnboardingAuditEvent)
class HrOnboardingAuditEventAdmin(ReadOnlyAdmin):
    list_display = ("action", "tenant_id", "case_id", "business_id", "occurred_at")
    list_filter = ("action",)


# 其余权威表全部只读注册
for model in (
    HrOnboardingTemplateVersion,
    HrOnboardingTaskDefinition,
    HrOnboardingStageTransition,
    HrReportDelay,
    HrReportCheckin,
    HrPrehireProfile,
    HrPrehirePortalAccess,
    HrOnboardingDataConflict,
    HrOnboardingMaterialRequirement,
    HrOnboardingMaterial,
    HrActivationAttempt,
    HrOnboardingActivationSnapshot,
    HrOnboardingTaskInstance,
    HrProvisioningRequest,
    HrProbationCase,
    HrProbationExtension,
):
    admin.site.register(model, ReadOnlyAdmin)
