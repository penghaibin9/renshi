"""
hr_onboarding/api/urls.py

HR05 API 路由。
- 管理端：/api/hr/v1/onboarding/*（登录 + 权限 + tenant fail-closed）
- Portal：/api/hr/v1/prehire/me/*（仅 token 鉴权，不接受任意 case id）
"""

from django.urls import path

from hr_onboarding.api import excel as excel_views
from hr_onboarding.api import materials as materials_views
from hr_onboarding.api import portal as portal_views
from hr_onboarding.api import probations as probations_views
from hr_onboarding.api import tasks as tasks_views
from hr_onboarding.api import views as api_views

urlpatterns = [
    # 探针
    path(
        "api/hr/v1/onboarding/health",
        api_views.hr05_api_health,
        name="hr05-api-health",
    ),
    path(
        "api/hr/v1/onboarding/contract",
        api_views.hr05_api_contract,
        name="hr05-api-contract",
    ),
    # HR05-01 待报到（S3）
    path(
        "api/hr/v1/onboarding/cases",
        api_views.hr05_cases_list,
        name="hr05-api-cases",
    ),
    path(
        "api/hr/v1/onboarding/cases/<uuid:case_id>",
        api_views.hr05_case_detail,
        name="hr05-api-case-detail",
    ),
    path(
        "api/hr/v1/onboarding/cases/<uuid:case_id>/confirm-intent",
        api_views.hr05_case_confirm_intent,
        name="hr05-api-case-confirm-intent",
    ),
    path(
        "api/hr/v1/onboarding/cases/<uuid:case_id>/request-delay",
        api_views.hr05_case_request_delay,
        name="hr05-api-case-request-delay",
    ),
    path(
        "api/hr/v1/onboarding/cases/<uuid:case_id>/decline",
        api_views.hr05_case_decline,
        name="hr05-api-case-decline",
    ),
    # HR05-02 报到登记 + Activation Gate（S4）
    path(
        "api/hr/v1/onboarding/cases/<uuid:case_id>/report",
        api_views.hr05_case_report,
        name="hr05-api-case-report",
    ),
    path(
        "api/hr/v1/onboarding/cases/<uuid:case_id>/activation-gate",
        api_views.hr05_case_activation_gate,
        name="hr05-api-case-activation-gate",
    ),
    path(
        "api/hr/v1/onboarding/cases/<uuid:case_id>/activate",
        api_views.hr05_case_activate,
        name="hr05-api-case-activate",
    ),
    # HR05-03 材料核验（S5）
    path(
        "api/hr/v1/onboarding/cases/<uuid:case_id>/materials",
        materials_views.materials_list,
        name="hr05-api-materials",
    ),
    path(
        "api/hr/v1/onboarding/cases/<uuid:case_id>/materials/<uuid:material_id>/submit",
        materials_views.material_submit,
        name="hr05-api-material-submit",
    ),
    path(
        "api/hr/v1/onboarding/materials/<uuid:material_id>/verify",
        materials_views.material_verify,
        name="hr05-api-material-verify",
    ),
    path(
        "api/hr/v1/onboarding/materials/<uuid:material_id>/return",
        materials_views.material_return,
        name="hr05-api-material-return",
    ),
    path(
        "api/hr/v1/onboarding/materials/<uuid:material_id>/waive",
        materials_views.material_waive,
        name="hr05-api-material-waive",
    ),
    path(
        "api/hr/v1/onboarding/materials/<uuid:material_id>/download-ticket",
        materials_views.material_download_ticket,
        name="hr05-api-material-download-ticket",
    ),
    path(
        "api/hr/v1/onboarding/materials/download",
        materials_views.material_download,
        name="hr05-api-material-download",
    ),
    # HR05-04 协同任务 + Provisioning（S6）
    path(
        "api/hr/v1/onboarding/cases/<uuid:case_id>/tasks",
        tasks_views.tasks_list,
        name="hr05-api-tasks",
    ),
    path(
        "api/hr/v1/onboarding/tasks/<uuid:task_id>/start",
        tasks_views.task_start,
        name="hr05-api-task-start",
    ),
    path(
        "api/hr/v1/onboarding/tasks/<uuid:task_id>/complete",
        tasks_views.task_complete,
        name="hr05-api-task-complete",
    ),
    path(
        "api/hr/v1/onboarding/tasks/<uuid:task_id>/waive",
        tasks_views.task_waive,
        name="hr05-api-task-waive",
    ),
    path(
        "api/hr/v1/onboarding/cases/<uuid:case_id>/provisionings",
        tasks_views.provisioning_request,
        name="hr05-api-provisioning-request",
    ),
    path(
        "api/hr/v1/onboarding/provisionings/<uuid:provisioning_id>/retry",
        tasks_views.provisioning_retry,
        name="hr05-api-provisioning-retry",
    ),
    # HR05-05 试用与转正（S7）
    path(
        "api/hr/v1/onboarding/probations",
        probations_views.probations_list,
        name="hr05-api-probations",
    ),
    path(
        "api/hr/v1/onboarding/cases/<uuid:case_id>/probations",
        probations_views.probation_open,
        name="hr05-api-probation-open",
    ),
    path(
        "api/hr/v1/onboarding/probations/<uuid:probation_id>/submit-review",
        probations_views.probation_submit_review,
        name="hr05-api-probation-review",
    ),
    path(
        "api/hr/v1/onboarding/probations/<uuid:probation_id>/confirm",
        probations_views.probation_confirm,
        name="hr05-api-probation-confirm",
    ),
    path(
        "api/hr/v1/onboarding/probations/<uuid:probation_id>/extend",
        probations_views.probation_extend,
        name="hr05-api-probation-extend",
    ),
    path(
        "api/hr/v1/onboarding/probations/<uuid:probation_id>/fail",
        probations_views.probation_fail,
        name="hr05-api-probation-fail",
    ),
    # Portal（S3）
    path(
        "api/hr/v1/prehire/me",
        portal_views.prehire_me,
        name="hr05-api-prehire-me",
    ),
    path(
        "api/hr/v1/prehire/me/profile",
        portal_views.prehire_update_profile,
        name="hr05-api-prehire-profile",
    ),
    path(
        "api/hr/v1/prehire/me/confirm-intent",
        portal_views.prehire_confirm_intent,
        name="hr05-api-prehire-confirm",
    ),
    # Excel 导入（S10）
    path(
        "api/hr/v1/onboarding/excel/template",
        excel_views.excel_template_download,
        name="hr05-api-excel-template",
    ),
    path(
        "api/hr/v1/onboarding/excel/upload",
        excel_views.excel_upload,
        name="hr05-api-excel-upload",
    ),
    path(
        "api/hr/v1/onboarding/excel/confirm",
        excel_views.excel_confirm,
        name="hr05-api-excel-confirm",
    ),
    path(
        "api/hr/v1/onboarding/excel/errors",
        excel_views.excel_error_workbook,
        name="hr05-api-excel-errors",
    ),
]
