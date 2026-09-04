from django.urls import path

from . import (
    api,
    archive_api,
    case_api,
    fact_api,
    legacy_api,
    participant_api,
    retirement_api,
)

app_name = "hr_exit_api"
urlpatterns = [
    path("dashboard/", api.dashboard, name="dashboard"),
    path(
        "legacy/reconcile/",
        legacy_api.legacy_reconciliation,
        name="legacy-reconcile",
    ),
    path("cases/", api.create_case, name="case-create"),
    path("cases/<uuid:case_id>/", case_api.amend_case, name="case-amend"),
    path("cases/<uuid:case_id>/submit/", api.submit_case, name="case-submit"),
    path("cases/<uuid:case_id>/return/", api.return_case, name="case-return"),
    path("cases/<uuid:case_id>/approve/", api.approve_case, name="case-approve"),
    path("cases/<uuid:case_id>/reject/", api.reject_case, name="case-reject"),
    path("cases/<uuid:case_id>/cancel/", api.cancel_case, name="case-cancel"),
    path(
        "cases/<uuid:case_id>/handover/start/",
        api.begin_handover,
        name="case-handover-start",
    ),
    path(
        "cases/<uuid:case_id>/settlement/start/",
        api.begin_settlement,
        name="case-settlement-start",
    ),
    path(
        "cases/<uuid:case_id>/apply-effect/",
        api.apply_effect,
        name="case-effect-apply",
    ),
    path(
        "effects/<uuid:effect_id>/participants/<str:participant>/execute/",
        participant_api.execute_participant,
        name="effect-participant-execute",
    ),
    path(
        "effects/<uuid:effect_id>/participants/reconcile/",
        participant_api.reconcile_participants,
        name="effect-participants-reconcile",
    ),
    path(
        "exit-facts/<uuid:exit_fact_id>/retirement/",
        retirement_api.finalize_retirement,
        name="retirement-finalize",
    ),
    path(
        "exit-facts/<uuid:fact_id>/correct/",
        fact_api.correct_exit_fact,
        name="exit-fact-correct",
    ),
    path(
        "exit-facts/<uuid:fact_id>/revoke/",
        fact_api.revoke_exit_fact,
        name="exit-fact-revoke",
    ),
    path(
        "retirement-facts/<uuid:retirement_fact_id>/pension-status/",
        retirement_api.set_pension_status,
        name="retirement-pension-status",
    ),
    path(
        "retirement-policies/",
        retirement_api.create_retirement_policy,
        name="retirement-policy-create",
    ),
    path(
        "retirement-policies/<uuid:policy_id>/activate/",
        retirement_api.activate_retirement_policy,
        name="retirement-policy-activate",
    ),
    path(
        "retirement-prechecks/",
        retirement_api.run_retirement_precheck,
        name="retirement-precheck-run",
    ),
    path(
        "cases/<uuid:case_id>/handover-items/",
        api.create_handover_item,
        name="handover-item-create",
    ),
    path(
        "handover-items/<uuid:item_id>/complete/",
        api.complete_handover_item,
        name="handover-item-complete",
    ),
    path(
        "handover-items/<uuid:item_id>/complete-upload/",
        api.complete_handover_item_upload,
        name="handover-item-complete-upload",
    ),
    path(
        "handover-items/<uuid:item_id>/evidence/download/",
        api.download_handover_evidence,
        name="handover-item-evidence-download",
    ),
    path(
        "handover-items/<uuid:item_id>/waive/",
        api.waive_handover_item,
        name="handover-item-waive",
    ),
    path(
        "cases/<uuid:case_id>/archive-transfers/",
        archive_api.case_archive_transfers,
        name="archive-transfer-list-create",
    ),
    path(
        "archive-transfers/<uuid:receipt_id>/send/",
        archive_api.send_archive_transfer,
        name="archive-transfer-send",
    ),
    path(
        "archive-transfers/<uuid:receipt_id>/receive/",
        archive_api.receive_archive_transfer,
        name="archive-transfer-receive",
    ),
    path(
        "archive-transfers/<uuid:receipt_id>/return/",
        archive_api.return_archive_transfer,
        name="archive-transfer-return",
    ),
    path(
        "archive-transfers/<uuid:receipt_id>/attachments/<str:attachment_role>/download/",
        archive_api.download_archive_attachment,
        name="archive-transfer-attachment-download",
    ),
]
