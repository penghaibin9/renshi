from datetime import datetime, timezone
from unittest.mock import Mock

from django.test import SimpleTestCase

from hr_control_center.context import HrRequestContext
from hr_control_center.providers.todo_base import (
    HrTodoProvider,
    TodoItem,
    TodoProviderUnavailable,
    TodoSummary,
)
from hr_control_center.providers.todo_registry import TodoProviderRegistry
from hr_control_center.services.todo_service import TodoService


class _OkProvider(HrTodoProvider):
    provider_key = "ok"

    def get_summary(self, context):
        return TodoSummary(overdue=1, today=2, week=3, total=4)

    def list_todos(self, context, filters=None, page=1, page_size=20):
        items = [
            TodoItem(
                provider=self.provider_key,
                business_type="case",
                business_id=str(i),
                title=f"item-{i}",
                is_overdue=i == 0,
                due_at=datetime(2026, 8, i + 1, tzinfo=timezone.utc),
            ).__dict__
            for i in range(6)
        ]
        start = (page - 1) * page_size
        return {"available": True, "total": len(items), "items": items[start:start + page_size]}


class _DownProvider(HrTodoProvider):
    provider_key = "down"

    def get_summary(self, context):
        raise TodoProviderUnavailable(self.provider_key, "UPSTREAM_TIMEOUT", "超时")

    def list_todos(self, context, filters=None, page=1, page_size=20):
        raise RuntimeError("boom")


class TodoServiceContractTests(SimpleTestCase):
    def setUp(self):
        self.context = HrRequestContext(tenant_id=1)

    def test_all_sources_down_is_unavailable_not_fake_zero(self):
        payload = TodoService([_DownProvider()]).get_summary(self.context)
        self.assertEqual(payload["status"], "UNAVAILABLE")
        self.assertIsNone(payload["total"])
        self.assertEqual(payload["sourceHealth"][0]["reasonCode"], "UPSTREAM_TIMEOUT")

    def test_partial_source_keeps_real_counts_and_health(self):
        payload = TodoService([_OkProvider(), _DownProvider()]).get_summary(self.context)
        self.assertEqual(payload["status"], "PARTIAL")
        self.assertEqual(payload["total"], 4)
        self.assertEqual(payload["partialSources"], ["down"])

    def test_global_page_two_is_not_double_paginated(self):
        payload = TodoService([_OkProvider()]).list_todos(
            self.context, page=2, page_size=2
        )
        self.assertEqual(payload["pagination"]["total"], 6)
        self.assertEqual(len(payload["items"]), 2)

    def test_overdue_item_sorts_before_non_overdue(self):
        payload = TodoService([_OkProvider()]).list_todos(
            self.context, page=1, page_size=6
        )
        self.assertEqual(payload["items"][0]["businessId"], "0")

    def test_todo_items_use_the_frozen_camel_case_api_contract(self):
        payload = TodoService([_OkProvider()]).list_todos(
            self.context, page=1, page_size=1
        )

        item = payload["items"][0]
        self.assertEqual(item["id"], "ok:0")
        self.assertEqual(item["businessType"], "case")
        self.assertIn("dueAt", item)
        self.assertIn("isOverdue", item)
        self.assertIn("actionUrl", item)
        self.assertNotIn("business_id", item)

    def test_missing_due_date_can_mix_with_timezone_aware_dates(self):
        provider = _OkProvider()
        original = provider.list_todos

        def with_missing_due(*args, **kwargs):
            result = original(*args, **kwargs)
            result["items"][0]["due_at"] = None
            return result

        provider.list_todos = with_missing_due
        payload = TodoService([provider]).list_todos(
            self.context, page=1, page_size=6
        )
        self.assertEqual(len(payload["items"]), 6)

    def test_provider_permission_is_trimmed_before_query(self):
        provider = _OkProvider()
        provider.required_permission = "hr.other.view"
        user = Mock(is_superuser=False)
        user.has_perm.return_value = False

        payload = TodoService([provider]).get_summary(self.context, user=user)

        self.assertEqual(payload["status"], "OK")
        self.assertEqual(payload["total"], 0)
        self.assertEqual(payload["sourceHealth"][0]["status"], "FILTERED")

    def test_registry_rejects_duplicate_key_with_different_provider(self):
        registry = TodoProviderRegistry()
        registry.register(_OkProvider)

        class Duplicate(HrTodoProvider):
            provider_key = "ok"

        with self.assertRaises(ValueError):
            registry.register(Duplicate)
