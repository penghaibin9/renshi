import inspect

from django.test import RequestFactory, SimpleTestCase

from hr_external.api import (
    hiring,
    industry,
    integration,
    materials,
    portal,
    renewal_exit,
    tasks,
    views,
)


class ExternalApiHttpMethodContractTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_mutating_endpoints_reject_get_before_business_logic(self):
        cases = (
            (integration.engagement_access_provision, ("00000000-0000-0000-0000-000000000001",)),
            (integration.engagement_access_revoke, ("00000000-0000-0000-0000-000000000001",)),
            (integration.reconciliation_run, ()),
            (renewal_exit.renewal_create, ("00000000-0000-0000-0000-000000000001",)),
            (renewal_exit.renewal_decide, ("00000000-0000-0000-0000-000000000001",)),
            (renewal_exit.exit_create, ("00000000-0000-0000-0000-000000000001",)),
            (renewal_exit.exit_prepare, ("00000000-0000-0000-0000-000000000001",)),
            (renewal_exit.exit_complete, ("00000000-0000-0000-0000-000000000001",)),
            (industry.workspace_create, ()),
            (industry.contribution_submit, ("00000000-0000-0000-0000-000000000001",)),
            (portal.portal_token_issue, ()),
            (hiring.hiring_create, ()),
            (hiring.hiring_validate, ("00000000-0000-0000-0000-000000000001",)),
            (hiring.hiring_submit, ("00000000-0000-0000-0000-000000000001",)),
            (hiring.hiring_return, ("00000000-0000-0000-0000-000000000001",)),
            (hiring.hiring_approve, ("00000000-0000-0000-0000-000000000001",)),
            (hiring.hiring_activate, ("00000000-0000-0000-0000-000000000001",)),
            (tasks.task_create, ()),
            (tasks.task_accept, ("00000000-0000-0000-0000-000000000001",)),
            (tasks.task_start, ("00000000-0000-0000-0000-000000000001",)),
            (tasks.task_submit, ("00000000-0000-0000-0000-000000000001",)),
            (tasks.task_verify, ("00000000-0000-0000-0000-000000000001",)),
            (tasks.workload_verify, ()),
            (tasks.settlement_create, ("00000000-0000-0000-0000-000000000001",)),
            (materials.material_download_ticket, ("00000000-0000-0000-0000-000000000001",)),
            (materials.material_upload, ("00000000-0000-0000-0000-000000000001",)),
            (views.identity_match, ()),
            (views.import_job_upload, ()),
            (views.import_job_validate, ("00000000-0000-0000-0000-000000000001",)),
            (views.import_job_confirm, ("00000000-0000-0000-0000-000000000001",)),
            (views.import_job_execute, ("00000000-0000-0000-0000-000000000001",)),
        )
        for view, args in cases:
            with self.subTest(view=inspect.unwrap(view).__name__):
                response = view(self.factory.get("/should-not-mutate"), *args)
                self.assertEqual(response.status_code, 405)

    def test_read_endpoints_reject_post(self):
        cases = (
            (integration.engagement_access, ("00000000-0000-0000-0000-000000000001",)),
            (integration.engagement_academic, ("00000000-0000-0000-0000-000000000001",)),
            (renewal_exit.renewal_list, ()),
            (renewal_exit.exit_detail, ("00000000-0000-0000-0000-000000000001",)),
            (industry.industry_list, ()),
            (industry.workspace_list, ()),
            (portal.portal_me, ()),
            (hiring.hiring_list, ()),
            (hiring.hiring_detail, ("00000000-0000-0000-0000-000000000001",)),
            (tasks.task_list, ()),
            (tasks.task_detail, ("00000000-0000-0000-0000-000000000001",)),
            (tasks.workload_list, ()),
            (materials.file_ticket_redeem, ()),
            (views.contract_probe, ()),
            (views.category_catalog, ()),
            (views.profile_detail, ("00000000-0000-0000-0000-000000000001",)),
            (views.profile_engagements, ("00000000-0000-0000-0000-000000000001",)),
            (views.profile_history, ("00000000-0000-0000-0000-000000000001",)),
        )
        for view, args in cases:
            with self.subTest(view=inspect.unwrap(view).__name__):
                response = view(self.factory.post("/read-only"), *args)
                self.assertEqual(response.status_code, 405)
