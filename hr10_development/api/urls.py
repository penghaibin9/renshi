"""
hr10_development/api/urls.py

HR10 API 路由。所有端点统一在 /api/v1/hr/development/ 下（00 §28.1 canonical root）。
内部 Provider API 在 /internal/hr/development/ 下。
"""

from django.urls import path

from hr10_development.api import (
    health, plans, programs, requests as request_api,
    enrollments, practice, practice_process, development_records, dashboard,
    internal, imports,
)

app_name = "hr10_development_api"

urlpatterns = [
    # Health
    path("api/v1/hr/development/health", health.health_check, name="health"),

    # ============ S2: Plans ============
    path("api/v1/hr/development/plans", plans.list_plans, name="plan-list"),
    path("api/v1/hr/development/plans/<int:plan_id>", plans.get_plan, name="plan-detail"),
    path("api/v1/hr/development/plans/create", plans.create_plan, name="plan-create"),
    path("api/v1/hr/development/plans/<int:plan_id>/submit", plans.submit_plan, name="plan-submit"),
    path("api/v1/hr/development/plans/<int:plan_id>/approve", plans.approve_plan, name="plan-approve"),
    path("api/v1/hr/development/plans/<int:plan_id>/return", plans.return_plan, name="plan-return"),
    path("api/v1/hr/development/plans/<int:plan_id>/reject", plans.reject_plan, name="plan-reject"),
    path("api/v1/hr/development/plans/<int:plan_id>/publish", plans.publish_plan, name="plan-publish"),
    path("api/v1/hr/development/plans/<int:plan_id>/close", plans.close_plan, name="plan-close"),
    path("api/v1/hr/development/plans/<int:plan_id>/versions", plans.create_plan_version, name="plan-create-version"),
    path("api/v1/hr/development/plans/<int:plan_id>/metrics", dashboard.plan_metrics, name="plan-metrics"),

    # ============ S3: Programs ============
    path("api/v1/hr/development/programs", programs.list_programs, name="program-list"),
    path("api/v1/hr/development/programs/<int:program_id>", programs.get_program, name="program-detail"),
    path("api/v1/hr/development/programs/create", programs.create_program, name="program-create"),
    path("api/v1/hr/development/programs/<int:program_id>/versions", programs.create_program_version, name="program-create-version"),
    path("api/v1/hr/development/programs/<int:program_id>/publish", programs.publish_program, name="program-publish"),
    path("api/v1/hr/development/offerings/create", programs.create_offering, name="offering-create"),
    path("api/v1/hr/development/offerings/<int:offering_id>", programs.get_offering, name="offering-detail"),
    path("api/v1/hr/development/offerings/<int:offering_id>/open-enrollment", programs.open_enrollment, name="offering-open-enrollment"),
    path("api/v1/hr/development/offerings/<int:offering_id>/cancel", programs.cancel_offering, name="offering-cancel"),
    path("api/v1/hr/development/offerings/<int:offering_id>/capacity", programs.get_offering_capacity, name="offering-capacity"),

    # ============ S4: Requests / Enrollment ============
    path("api/v1/hr/development/requests", request_api.list_requests, name="request-list"),
    path("api/v1/hr/development/requests/create", request_api.create_request, name="request-create"),
    path("api/v1/hr/development/requests/<int:request_id>", request_api.get_request, name="request-detail"),
    path("api/v1/hr/development/requests/<int:request_id>/submit", request_api.submit_request, name="request-submit"),
    path("api/v1/hr/development/requests/<int:request_id>/approve", request_api.approve_request, name="request-approve"),
    path("api/v1/hr/development/requests/<int:request_id>/return", request_api.return_request, name="request-return"),
    path("api/v1/hr/development/requests/<int:request_id>/reject", request_api.reject_request, name="request-reject"),
    path("api/v1/hr/development/requests/<int:request_id>/withdraw", request_api.withdraw_request, name="request-withdraw"),
    path("api/v1/hr/development/offerings/<int:offering_id>/enroll", request_api.enroll_in_offering, name="offering-enroll"),
    path("api/v1/hr/development/offerings/<int:offering_id>/waitlist", request_api.waitlist_offering, name="offering-waitlist"),
    path("api/v1/hr/development/enrollments/<int:enrollment_id>/complete", enrollments.complete_enrollment, name="enrollment-complete"),
    path("api/v1/hr/development/enrollments/<int:enrollment_id>/verify-completion", enrollments.verify_completion, name="enrollment-verify-completion"),

    # ============ S6: Enterprise Practice ============
    path("api/v1/hr/development/practice-projects", practice.list_projects, name="practice-project-list"),
    path("api/v1/hr/development/practice-projects/create", practice.create_project, name="practice-project-create"),
    path("api/v1/hr/development/practice-projects/<int:project_id>", practice.get_project, name="practice-project-detail"),
    path("api/v1/hr/development/practice-projects/<int:project_id>/versions", practice.create_project_version, name="practice-project-create-version"),
    path("api/v1/hr/development/practice-projects/<int:project_id>/publish", practice.publish_project, name="practice-project-publish"),
    path("api/v1/hr/development/practice-placements/create", practice.create_placement, name="practice-placement-create"),
    path("api/v1/hr/development/practice-assignments/create", practice.create_assignment, name="practice-assignment-create"),
    path("api/v1/hr/development/practice-assignments/<int:assignment_id>/start", practice.start_assignment, name="practice-assignment-start"),
    path("api/v1/hr/development/practice-assignments/<int:assignment_id>/suspend", practice.suspend_assignment, name="practice-assignment-suspend"),
    path("api/v1/hr/development/practice-assignments/<int:assignment_id>/resume", practice.resume_assignment, name="practice-assignment-resume"),

    # ============ S7: Practice Process / Output ============
    path("api/v1/hr/development/practice-assignments/<int:assignment_id>/activities", practice_process.add_activity, name="practice-activity-add"),
    path("api/v1/hr/development/practice-assignments/<int:assignment_id>/evidence", practice_process.add_evidence, name="practice-evidence-add"),
    path("api/v1/hr/development/practice-assignments/<int:assignment_id>/mentor-feedback", practice_process.submit_mentor_feedback, name="practice-mentor-feedback"),
    path("api/v1/hr/development/practice-assignments/<int:assignment_id>/school-evaluation", practice_process.submit_school_evaluation, name="practice-school-evaluation"),
    path("api/v1/hr/development/practice-assignments/<int:assignment_id>/submit-completion", practice_process.submit_completion, name="practice-submit-completion"),
    path("api/v1/hr/development/practice-assignments/<int:assignment_id>/finalize", practice_process.finalize_evaluation, name="practice-finalize"),
    path("api/v1/hr/development/development-outputs/create", practice_process.create_output, name="output-create"),
    path("api/v1/hr/development/development-outputs/<int:output_id>/verify", practice_process.verify_output, name="output-verify"),

    # ============ S8: Development Records / Dashboard / Metrics ============
    path("api/v1/hr/development/development-records/<int:staff_id>", development_records.get_record_summary, name="record-summary"),
    path("api/v1/hr/development/development-records/<int:staff_id>/facts", development_records.get_facts, name="record-facts"),
    path("api/v1/hr/development/development-records/<int:staff_id>/ledger", development_records.get_ledger, name="record-ledger"),
    path("api/v1/hr/development/development-records/<int:staff_id>/compliance", development_records.get_compliance, name="record-compliance"),
    path("api/v1/hr/development/development-records/<int:staff_id>/risks", development_records.get_risks, name="record-risks"),
    path("api/v1/hr/development/dashboard", dashboard.dashboard, name="development-dashboard"),
    path("api/v1/hr/development/metrics/<str:metric_code>", dashboard.metric_detail, name="development-metric"),

    # ============ Excel Import (S10) ============
    path("api/v1/hr/development/imports/upload", imports.upload_import, name="import-upload"),
    path("api/v1/hr/development/imports/<int:job_id>/validate", imports.validate_import, name="import-validate"),
    path("api/v1/hr/development/imports/<int:job_id>/confirm", imports.confirm_import, name="import-confirm"),
    path("api/v1/hr/development/imports/<int:job_id>", imports.get_import_status, name="import-status"),

    # ============ Internal Provider APIs (S9) ============
    path("internal/hr/development/evidence/staff/<str:staff_id>", internal.get_hr09_evidence, name="internal-hr09-evidence"),
    path("internal/hr/development/time-windows/staff/<str:staff_id>", internal.get_development_time_windows, name="internal-hr11-time-windows"),
]
