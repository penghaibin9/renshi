from django.urls import path

from . import api, setup_api, policy_api

app_name = "hr_payroll_api"
urlpatterns = [
    path("policy/options/", policy_api.options, name="policy-options"),
    path("policy/config/<str:kind>/", policy_api.configurations, name="policy-config"),
    path("policy/config/<str:kind>/<uuid:object_id>/publish/", policy_api.publish_configuration, name="policy-publish"),
    path("policy/trials/", policy_api.trials, name="policy-trials"),
    path("policy/trials/<uuid:trial_id>/", policy_api.trial_detail, name="policy-trial-detail"),
    path("policy/trials/<uuid:trial_id>/review/", policy_api.review_trial, name="policy-trial-review"),
    path("policy/tax-accounts/", policy_api.tax_accounts, name="policy-tax-accounts"),
    path("policy/settlements/", policy_api.settlement_status, name="policy-settlements"),
    path("dashboard/", api.dashboard, name="dashboard"),
    path("setup-options/", setup_api.setup_options, name="setup-options"),
    path("profiles/", setup_api.create_profile, name="profile-create"),
    path("periods/", setup_api.create_period, name="period-create"),
    path("periods/<uuid:period_id>/freeze-input/", setup_api.freeze_period_input, name="period-freeze-input"),
    path("rules/", api.salary_rules, name="salary-rules"),
    path("rules/<uuid:rule_id>/publish/", api.publish_salary_rule, name="salary-rule-publish"),
    path("compensation-changes/", api.compensation_changes, name="compensation-changes"),
    path("compensation-changes/<uuid:case_id>/submit/", api.submit_compensation_change, name="compensation-change-submit"),
    path("compensation-changes/<uuid:case_id>/approve/", api.approve_compensation_change, name="compensation-change-approve"),
    path("compensation-changes/<uuid:case_id>/reject/", api.reject_compensation_change, name="compensation-change-reject"),
    path("benefit-plans/", api.benefit_plans, name="benefit-plans"),
    path(
        "benefit-plans/<uuid:plan_id>/publish/",
        api.publish_benefit_plan,
        name="benefit-plan-publish",
    ),
    path(
        "benefit-enrollments/",
        api.benefit_enrollments,
        name="benefit-enrollments",
    ),
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
    path(
        "results/<uuid:source_result_id>/reversal/",
        api.reverse_result,
        name="result-reversal",
    ),
]

urlpatterns += [
 path("policy/import/<str:kind>/template/", policy_api.import_template),
 path("policy/import/<str:kind>/preview/", policy_api.import_preview),
 path("policy/import-stage/<uuid:stage_id>/confirm/", policy_api.import_confirm),
 path("policy/import-stage/<uuid:stage_id>/errors/", policy_api.import_errors),
]

urlpatterns += [path("policy/retro/trials/",policy_api.retro_trial),path("policy/retro/<uuid:trial_id>/apply/",policy_api.retro_apply)]

urlpatterns += [path("policy/trials/<uuid:trial_id>/export.xlsx",policy_api.export_trial)]
