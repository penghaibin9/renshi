"""
admin.py

This page is used to register base models with admins site.
"""

from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from base.models import (
    Announcement,
    Attachment,
    AttendanceAllowedIP,
    Company,
    CompanyGroupAssignment,
    CompanyLeaves,
    DashboardEmployeeCharts,
    Department,
    DynamicEmailConfiguration,
    DynamicPagination,
    EmailLog,
    EmployeeShift,
    EmployeeShiftDay,
    EmployeeShiftSchedule,
    EmployeeType,
    Holidays,
    JobPosition,
    JobRole,
    MultipleApprovalCondition,
    MultipleApprovalManagers,
    PenaltyAccounts,
    RotatingShift,
    RotatingShiftAssign,
    RotatingWorkType,
    RotatingWorkTypeAssign,
    ShiftRequest,
    ShiftRequestComment,
    Tags,
    WorkType,
    WorkTypeRequest,
    WorkTypeRequestComment,
)

# Register your models here.

admin.site.register(CompanyGroupAssignment)
admin.site.register(Company)
admin.site.register(Department, SimpleHistoryAdmin)
admin.site.register(JobPosition)
admin.site.register(JobRole)
admin.site.register(EmployeeShift)
admin.site.register(EmployeeShiftSchedule)
admin.site.register(EmployeeShiftDay)
admin.site.register(EmployeeType)
admin.site.register(WorkType)
admin.site.register(RotatingWorkType)
admin.site.register(RotatingWorkTypeAssign)
admin.site.register(RotatingShift)
admin.site.register(RotatingShiftAssign)
admin.site.register(ShiftRequest)
admin.site.register(WorkTypeRequest)
admin.site.register(Tags)
admin.site.register(DynamicEmailConfiguration)
admin.site.register(MultipleApprovalManagers)
admin.site.register(ShiftRequestComment)
admin.site.register(WorkTypeRequestComment)
admin.site.register(DynamicPagination)
admin.site.register(Announcement)
admin.site.register(Attachment)


@admin.register(EmailLog)
class EmailLogAdmin(admin.ModelAdmin):
    list_display = ("subject", "to", "status", "company_id", "created_at")
    list_filter = ("status", "company_id", "created_at")
    search_fields = ("subject", "to", "from_email")
    readonly_fields = (
        "subject",
        "body",
        "from_email",
        "to",
        "status",
        "company_id",
        "created_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
admin.site.register(DashboardEmployeeCharts)
admin.site.register(Holidays)
admin.site.register(CompanyLeaves)
admin.site.register(PenaltyAccounts)
admin.site.register(MultipleApprovalCondition)
admin.site.register(AttendanceAllowedIP)
