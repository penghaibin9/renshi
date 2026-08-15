"""Negative/bypass contract for the Legacy Write Authority Core."""

import json
from types import SimpleNamespace

from django.conf import settings
from django.core.cache import cache
from django.http import QueryDict
from django.test import RequestFactory, SimpleTestCase

from horilla.horilla_middlewares import _thread_locals
from horilla.legacy_hr_cutover import (
    LEGACY_WRITE_ATTEMPT_EVENT,
    LEGACY_WRITE_ATTEMPTS_CACHE_KEY,
    WRITE_SURFACE_REGISTRY,
    LegacyFormalWriteFrozenError,
    LegacyWriteAuthorityMiddleware,
    LegacyWriteAuthorityRouter,
    get_legacy_write_attempts_total,
    protect_retired_legacy_model_write,
    resolve_model_candidates,
    resolve_retired_legacy_target,
    semantic_write_intent,
)


class _Session(dict):
    session_key = "legacy-authority-test-session"


class _Meta:
    app_label = "payroll"
    object_name = "Payslip"
    model_name = "payslip"


class _RetiredPayrollModel:
    _meta = _Meta()


class _SafeMeta:
    app_label = "employee"
    object_name = "Employee"
    model_name = "employee"


class _SafeModel:
    _meta = _SafeMeta()


class _ViewMetadata:
    model = _RetiredPayrollModel


class LegacyWriteAuthorityCoreTests(SimpleTestCase):
    def setUp(self):
        cache.delete(LEGACY_WRITE_ATTEMPTS_CACHE_KEY)
        _thread_locals.request = None
        self.factory = RequestFactory()

    def tearDown(self):
        _thread_locals.request = None
        cache.delete(
            f"{_Session.session_key}cbvemployee_id"
        )

    def _request(self, method="get", path="/write/", **kwargs):
        request = getattr(self.factory, method)(path, **kwargs)
        request.session = _Session()
        return request

    def test_write_surface_registry_marks_get_kanban_as_semantic_write(self):
        self.assertTrue(
            WRITE_SURFACE_REGISTRY["update-kanban-sequence"]["semantic_write"]
        )
        request = self._request("get", "/update-kanban-sequence/")
        self.assertTrue(
            semantic_write_intent(
                request,
                surface="update-kanban-sequence",
            )
        )

    def test_resolver_covers_json_get_post_url_session_view_and_final_orm(self):
        request = SimpleNamespace(
            content_type="application/json",
            body=json.dumps(
                {"target": {"model": "payroll.Payslip"}}
            ).encode("utf-8"),
            encoding="utf-8",
            GET=QueryDict("model=employee.Employee"),
            POST=QueryDict("model_path=offboarding.OffboardingStage"),
            session=_Session(
                {
                    "authority": {
                        "model": "report.DynamicReport",
                    }
                }
            ),
            resolver_match=None,
            method="POST",
            path="/write/",
        )

        candidates = resolve_model_candidates(
            request,
            url_kwargs={
                "app_label": "payroll",
                "model_name": "Payslip",
            },
            view=_ViewMetadata,
            resolved_model=_RetiredPayrollModel,
        )
        sources = {candidate.source for candidate in candidates}
        paths = {candidate.model_path for candidate in candidates}

        self.assertIn("json.target:model", sources)
        self.assertIn("get:model", sources)
        self.assertIn("post:model_path", sources)
        self.assertIn("url_kwargs:model_name", sources)
        self.assertIn("session.authority:model", sources)
        self.assertIn("view:model", sources)
        self.assertIn("orm-resolved", sources)
        self.assertIn("payroll.Payslip", paths)
        self.assertIn("offboarding.OffboardingStage", paths)
        self.assertIn("report.DynamicReport", paths)

    def test_resolver_reads_horilla_dynamic_cache_model(self):
        request = self._request(
            "get",
            "/dynamic-path/employee_id/",
            data={"field": "employee_id"},
        )
        cache.set(
            f"{request.session.session_key}cbvemployee_id",
            {
                "dynamic_field": "employee_id",
                "model": _RetiredPayrollModel,
            },
        )

        target = resolve_retired_legacy_target(request)
        self.assertIsNotNone(target)
        self.assertEqual(target.model_path, "payroll.Payslip")
        self.assertEqual(
            target.source,
            "dynamic_cache:employee_id:model",
        )

    def test_decoy_safe_parameter_cannot_hide_final_retired_orm_model(self):
        request = self._request(
            "get",
            "/update-kanban-sequence/?model=employee.Employee",
        )
        target = resolve_retired_legacy_target(
            request,
            resolved_model=_RetiredPayrollModel,
        )
        self.assertIsNotNone(target)
        self.assertEqual(target.source, "orm-resolved")
        self.assertEqual(target.model_path, "payroll.Payslip")

    def test_outer_guard_blocks_retired_model_supplied_only_in_json(self):
        request = self.factory.post(
            "/generic-write/",
            data=json.dumps({"payload": {"model": "report.DynamicReport"}}),
            content_type="application/json",
        )
        request.session = _Session()
        called = []

        def unsafe_view(_request, *args, **kwargs):
            called.append(True)
            return None

        guarded = protect_retired_legacy_model_write(
            unsafe_view,
            surface="dynamic-form",
        )

        with self.assertLogs("renshi.legacy_cutover", level="WARNING") as logs:
            response = guarded(request)

        self.assertEqual(response.status_code, 410)
        self.assertEqual(called, [])
        self.assertEqual(get_legacy_write_attempts_total(), 1)
        self.assertIn(LEGACY_WRITE_ATTEMPT_EVENT, logs.output[0])

    def test_final_router_blocks_actual_retired_orm_model_on_get(self):
        request = self._request(
            "get",
            "/update-kanban-sequence/?model=employee.Employee",
        )
        _thread_locals.request = request
        router = LegacyWriteAuthorityRouter()

        with self.assertLogs("renshi.legacy_cutover", level="WARNING") as logs:
            with self.assertRaises(LegacyFormalWriteFrozenError) as raised:
                router.db_for_write(_RetiredPayrollModel)

        self.assertEqual(raised.exception.model_path, "payroll.Payslip")
        self.assertEqual(get_legacy_write_attempts_total(), 1)
        self.assertEqual(len(logs.output), 1)

    def test_final_router_does_not_touch_non_retired_models(self):
        request = self._request("post", "/safe-write/")
        _thread_locals.request = request
        router = LegacyWriteAuthorityRouter()

        self.assertIsNone(router.db_for_write(_SafeModel))
        self.assertEqual(get_legacy_write_attempts_total(), 0)

    def test_final_router_is_request_bound_so_migrations_reconciliation_are_not_sealed(self):
        _thread_locals.request = None
        router = LegacyWriteAuthorityRouter()

        self.assertIsNone(router.db_for_write(_RetiredPayrollModel))
        self.assertEqual(get_legacy_write_attempts_total(), 0)

    def test_exception_middleware_returns_same_410_contract_without_double_count(self):
        request = self._request("get", "/dynamic-write/")
        exception = LegacyFormalWriteFrozenError(
            model_path="payroll.Payslip",
            surface="orm-resolved-write",
            recorded=True,
        )
        middleware = LegacyWriteAuthorityMiddleware(lambda _request: None)

        response = middleware.process_exception(request, exception)

        self.assertEqual(response.status_code, 410)
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertEqual(response["Deprecation"], "true")
        self.assertEqual(get_legacy_write_attempts_total(), 0)

    def test_runtime_bootstrap_installs_final_router_and_context_cleanup(self):
        self.assertIn(
            "horilla.legacy_hr_cutover.LegacyWriteAuthorityRouter",
            settings.DATABASE_ROUTERS,
        )
        self.assertIn(
            "horilla.horilla_middlewares.ThreadLocalMiddleware",
            settings.MIDDLEWARE,
        )
        self.assertIn(
            "horilla.legacy_hr_cutover.LegacyWriteAuthorityMiddleware",
            settings.MIDDLEWARE,
        )
