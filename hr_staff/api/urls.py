"""
hr_staff/api/urls.py —— HR03 API 路由。

前缀：/api/hr/v1/staff/*
- S1: contract 探针
- S4: staff list
- S5: profile
- S6: assignments / employment-relationships / timeline
- S7: backgrounds
- S8: materials
- S9: corrections
"""

from django.urls import path

from hr_staff.api import views as api_views
from hr_staff.api import assignments as assignments_api
from hr_staff.api import backgrounds as backgrounds_api
from hr_staff.api import corrections as corrections_api
from hr_staff.api import data_quality as dq_api
from hr_staff.api import decisions as decisions_api
from hr_staff.api import export as export_api
from hr_staff.api import imports as imports_api
from hr_staff.api import materials as materials_api
from hr_staff.api import material_requests as mr_api
from hr_staff.api import sensitive as sensitive_api
from hr_staff.api import staff as staff_api
from hr_staff.api import profile as profile_api

urlpatterns = [
    path(
        "api/hr/v1/staff/contract",
        api_views.contract_probe,
        name="hr03-api-contract",
    ),
    path(
        "api/hr/v1/staff",
        staff_api.staff_list,
        name="hr03-api-staff-list",
    ),
    path(
        "api/hr/v1/staff/<uuid:staff_id>/profile",
        profile_api.profile_bootstrap,
        name="hr03-api-staff-profile",
    ),
    path(
        "api/hr/v1/staff/<uuid:staff_id>/assignments",
        assignments_api.assignments,
        name="hr03-api-staff-assignments",
    ),
    path(
        "api/hr/v1/staff/<uuid:staff_id>/employment-relationships",
        assignments_api.employment_relationships,
        name="hr03-api-staff-relationships",
    ),
    path(
        "api/hr/v1/staff/<uuid:staff_id>/timeline",
        assignments_api.timeline,
        name="hr03-api-staff-timeline",
    ),
    path(
        "api/hr/v1/staff/<uuid:staff_id>/backgrounds",
        backgrounds_api.backgrounds,
        name="hr03-api-staff-backgrounds",
    ),
    path(
        "api/hr/v1/staff/<uuid:staff_id>/personnel-decisions",
        decisions_api.personnel_decisions,
        name="hr03-api-personnel-decisions",
    ),
    path(
        "api/hr/v1/staff/<uuid:staff_id>/personnel-decisions/create",
        decisions_api.create_personnel_decision,
        name="hr03-api-personnel-decision-create",
    ),
    path(
        "api/hr/v1/personnel-decisions/<uuid:decision_id>/correct",
        decisions_api.correct_personnel_decision,
        name="hr03-api-personnel-decision-correct",
    ),
    path(
        "api/hr/v1/personnel-decisions/<uuid:decision_id>/revoke",
        decisions_api.revoke_personnel_decision,
        name="hr03-api-personnel-decision-revoke",
    ),
    path(
        "api/hr/v1/staff/<uuid:staff_id>/backgrounds/<str:kind>",
        backgrounds_api.add_background,
        name="hr03-api-staff-backgrounds-add",
    ),
    path(
        "api/hr/v1/staff/<uuid:staff_id>/materials",
        materials_api.materials,
        name="hr03-api-staff-materials",
    ),
    path(
        "api/hr/v1/staff/<uuid:staff_id>/materials/<uuid:material_id>/versions",
        materials_api.material_versions,
        name="hr03-api-staff-material-versions",
    ),
    path(
        "api/hr/v1/staff/<uuid:staff_id>/materials/<uuid:material_id>/download-ticket",
        materials_api.material_download_ticket,
        name="hr03-api-staff-material-download-ticket",
    ),
    path(
        "api/hr/v1/staff/<uuid:staff_id>/materials/<uuid:material_id>/download/<str:ticket>",
        materials_api.material_download,
        name="hr03-api-staff-material-download",
    ),
    path(
        "api/hr/v1/staff/<uuid:staff_id>/materials/<uuid:material_id>/verify",
        materials_api.material_verify,
        name="hr03-api-staff-material-verify",
    ),
    path(
        "api/hr/v1/staff/<uuid:staff_id>/corrections",
        corrections_api.create_correction,
        name="hr03-api-staff-corrections-create",
    ),
    path(
        "api/hr/v1/staff/<uuid:staff_id>/corrections/list",
        corrections_api.list_corrections,
        name="hr03-api-staff-corrections-list",
    ),
    path(
        "api/hr/v1/corrections/<uuid:case_id>",
        corrections_api.correction_detail,
        name="hr03-api-correction-detail",
    ),
    path(
        "api/hr/v1/corrections/<uuid:case_id>/submit",
        corrections_api.submit_correction,
        name="hr03-api-correction-submit",
    ),
    path(
        "api/hr/v1/corrections/<uuid:case_id>/review",
        corrections_api.review_correction,
        name="hr03-api-correction-review",
    ),
    path(
        "api/hr/v1/corrections/<uuid:case_id>/return",
        corrections_api.return_correction,
        name="hr03-api-correction-return",
    ),
    path(
        "api/hr/v1/corrections/<uuid:case_id>/resubmit",
        corrections_api.resubmit_correction,
        name="hr03-api-correction-resubmit",
    ),
    path(
        "api/hr/v1/corrections/<uuid:case_id>/approve",
        corrections_api.approve_correction,
        name="hr03-api-correction-approve",
    ),
    path(
        "api/hr/v1/corrections/<uuid:case_id>/reject",
        corrections_api.reject_correction,
        name="hr03-api-correction-reject",
    ),
    path(
        "api/hr/v1/corrections/<uuid:case_id>/cancel",
        corrections_api.cancel_correction,
        name="hr03-api-correction-cancel",
    ),
    path(
        "api/hr/v1/corrections/<uuid:case_id>/apply",
        corrections_api.apply_correction,
        name="hr03-api-correction-apply",
    ),
    path(
        "api/hr/v1/staff/<uuid:staff_id>/sensitive-fields/<str:field_code>/reveal",
        sensitive_api.reveal_field,
        name="hr03-api-staff-sensitive-reveal",
    ),
    path(
        "api/hr/v1/staff/search-by-identity",
        sensitive_api.search_by_identity,
        name="hr03-api-staff-search-by-identity",
    ),
    path(
        "api/hr/v1/staff/export",
        export_api.create_export,
        name="hr03-api-staff-export",
    ),
    path(
        "api/hr/v1/staff/export/<uuid:job_id>/download",
        export_api.download_export,
        name="hr03-api-staff-export-download",
    ),
    path(
        "api/hr/v1/staff/import",
        imports_api.upload_import,
        name="hr03-api-staff-import",
    ),
    path(
        "api/hr/v1/staff/import/<uuid:job_id>/commit",
        imports_api.commit_import,
        name="hr03-api-staff-import-commit",
    ),
    path(
        "api/hr/v1/staff/import/<uuid:job_id>",
        imports_api.import_status,
        name="hr03-api-staff-import-status",
    ),
    path(
        "api/hr/v1/staff/data-quality-scan",
        dq_api.scan,
        name="hr03-api-staff-data-quality-scan",
    ),
    path(
        "api/hr/v1/staff/<uuid:staff_id>/material-requests",
        mr_api.list_requests,
        name="hr03-api-staff-material-requests-list",
    ),
    path(
        "api/hr/v1/staff/<uuid:staff_id>/material-requests/create",
        mr_api.create_request,
        name="hr03-api-staff-material-requests-create",
    ),
]
