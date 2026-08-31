from django.urls import path

from . import api

app_name = "hr_payroll_api"
urlpatterns = [
    path("dashboard/", api.dashboard, name="dashboard"),
    path("rules/", api.salary_rules, name="salary-rules"),
    path("rules/<uuid:rule_id>/publish/", api.publish_salary_rule, name="salary-rule-publish"),
    path("statutory-rules/", api.statutory_rules, name="statutory-rules"),
    path("statutory-rules/<uuid:rule_id>/publish/", api.publish_statutory_rule, name="statutory-rule-publish"),
    path("results/<uuid:result_id>/statutory-contributions/", api.statutory_contributions, name="result-statutory-contributions"),
    path("periods/<uuid:period_id>/inputs/", api.capture_period_input, name="period-input"),
    path("periods/<uuid:period_id>/calculations/", api.calculate_period, name="period-calculate"),
    path("results/<uuid:result_id>/review/", api.review_result, name="result-review"),
    path("periods/<uuid:period_id>/review-complete/", api.complete_period_review, name="period-review-complete"),
    path("periods/<uuid:period_id>/finalize/", api.finalize_period, name="period-finalize"),
    path("results/<uuid:result_id>/payments/", api.create_payment, name="result-payment"),
    path("payments/<uuid:instruction_id>/send/", api.send_payment, name="payment-send"),
    path("payments/<uuid:instruction_id>/receipts/", api.receive_payment, name="payment-receipt"),
    path("results/<uuid:result_id>/payslips/", api.publish_payslip, name="result-payslip"),
    path("payments/<uuid:instruction_id>/reconciliation/", api.reconcile_payment, name="payment-reconcile"),
    path(
        "legacy-reconciliation/",
        api.legacy_reconciliation,
        name="legacy-reconciliation",
    ),
    path(
        "legacy-takeover/inventories/",
        api.legacy_takeover_inventories,
        name="legacy-takeover-inventories",
    ),
    path(
        "legacy-takeover/activate/",
        api.activate_legacy_takeover,
        name="legacy-takeover-activate",
    ),
    path(
        "legacy-takeover/write-block-audits/",
        api.legacy_write_block_audits,
        name="legacy-takeover-write-block-audits",
    ),
    path(
        "results/<uuid:source_result_id>/adjustments/",
        api.adjust_result,
        name="result-adjustments",
    ),
]
