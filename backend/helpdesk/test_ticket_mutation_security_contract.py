"""Regression contracts for helpdesk ticket mutations."""

import ast
from pathlib import Path

from django.test import SimpleTestCase


class HelpdeskTicketMutationSecurityContractTests(SimpleTestCase):
    backend_dir = Path(__file__).resolve().parent.parent

    def _function_source(self, function_name):
        path = self.backend_dir / "helpdesk/views.py"
        module_source = path.read_text(encoding="utf-8")
        module_lines = module_source.splitlines(keepends=True)
        functions = {
            node.name: node
            for node in ast.parse(module_source).body
            if isinstance(node, ast.FunctionDef)
        }
        node = functions[function_name]
        first_line = min(
            [node.lineno] + [decorator.lineno for decorator in node.decorator_list]
        )
        return "".join(module_lines[first_line - 1 : node.end_lineno])

    def test_core_ticket_mutators_are_post_only_and_atomic(self):
        for function_name in (
            "ticket_archive",
            "ticket_delete",
            "ticket_status_change",
            "comment_delete",
            "claim_ticket",
            "approve_claim_request",
            "tickets_bulk_archive",
            "tickets_bulk_delete",
            "change_ticket_status",
            "comment_edit",
        ):
            with self.subTest(function=function_name):
                source = self._function_source(function_name)
                self.assertIn("@require_POST", source)
                self.assertIn("transaction.atomic", source)
                self.assertIn("select_for_update()", source)

    def test_claim_decision_uses_locked_claim_ticket_and_posted_whitelist(self):
        source = self._function_source("approve_claim_request")
        self.assertIn("ClaimRequest.objects.select_for_update()", source)
        self.assertIn("Ticket.objects.select_for_update()", source)
        self.assertIn('request.POST.get("approve", "").lower()', source)
        self.assertIn('decision not in {"true", "false"}', source)
        self.assertIn("return handle_no_permission(request)", source)
        self.assertIn(
            "if claim_request.is_approved and employee in ticket.assigned_to.all()",
            source,
        )
        self.assertIn("_notify_after_commit", source)

    def test_ticket_notifications_and_mail_start_after_commit(self):
        for function_name in ("ticket_status_change", "ticket_delete"):
            source = self._function_source(function_name)
            self.assertIn("_notify_after_commit", source)
            self.assertIn("_start_thread_after_commit", source)

    def test_claim_and_comment_models_are_tenant_scoped(self):
        source = (self.backend_dir / "helpdesk/models.py").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            'related_company_field="ticket_id__employee_id__employee_work_info__company_id"',
            source,
        )
        self.assertIn(
            'related_company_field="ticket__employee_id__employee_work_info__company_id"',
            source,
        )

    def test_ticket_templates_do_not_mutate_with_get_links(self):
        templates = (
            self.backend_dir / "helpdesk/templates",
            self.backend_dir / "horilla_theme/templates/helpdesk",
        )
        combined = "\n".join(
            path.read_text(encoding="utf-8")
            for root in templates
            for path in root.rglob("*.html")
        )
        for fragment in (
            "hx-get = \"{% url 'ticket-archive'",
            "hx-get=\"{% url 'approve-claim-request'",
            "href=\"{% url 'comment-delete'",
            "href=\"{% url 'claim-ticket'",
        ):
            with self.subTest(fragment=fragment):
                self.assertNotIn(fragment, combined)

    def test_bulk_archive_state_is_posted_and_all_rows_must_be_in_scope(self):
        source = self._function_source("tickets_bulk_archive")
        self.assertIn('request.POST.get("is_active"', source)
        self.assertNotIn("request.GET", source)
        self.assertIn("tickets.count() != len(ids)", source)

        script = (
            self.backend_dir / "helpdesk/static/tickets/action.js"
        ).read_text(encoding="utf-8")
        self.assertNotIn("tickets-bulk-archive/?is_active=", script)
        self.assertIn('is_active: "False"', script)
        self.assertIn('is_active: "True"', script)

    def test_bulk_delete_is_all_or_nothing_and_defers_side_effects(self):
        source = self._function_source("tickets_bulk_delete")
        self.assertIn("len(tickets) != len(ids)", source)
        self.assertIn('ticket.status != "new"', source)
        self.assertIn("transaction.set_rollback(True)", source)
        self.assertIn("transaction.on_commit", source)

    def test_comment_edit_id_is_posted_and_locked(self):
        source = self._function_source("comment_edit")
        self.assertIn('request.POST.get("comment_id")', source)
        self.assertNotIn("request.GET", source)

        template = (
            self.backend_dir
            / "horilla_theme/templates/helpdesk/ticket/ticket_detail.html"
        ).read_text(encoding="utf-8")
        self.assertNotIn("comment-edit' %}?comment_id=", template)
        self.assertIn('hx-vals=\'{"comment_id":"{{ item.comment.id }}"}\'', template)

    def test_secondary_helpdesk_mutators_are_post_only_and_locked(self):
        for function_name in (
            "faq_category_delete",
            "faq_delete",
            "remove_tag",
            "delete_ticket_document",
            "delete_department_manager",
            "update_priority",
        ):
            with self.subTest(function=function_name):
                source = self._function_source(function_name)
                self.assertIn("@require_POST", source)
                self.assertIn("transaction.atomic", source)
                self.assertIn("select_for_update()", source)

    def test_attachment_delete_checks_the_attachment_ticket_not_url_id_aliases(self):
        source = self._function_source("delete_ticket_document")
        self.assertNotIn("@ticket_owner_can_enter", source)
        self.assertIn("document_obj.ticket", source)
        self.assertIn('request.user.has_perm("helpdesk.delete_attachment")', source)
        self.assertIn("comment_owner", source)

    def test_ticket_attachment_template_uses_post(self):
        source = (
            self.backend_dir / "helpdesk/templates/helpdesk/ticket/ticket_detail.html"
        ).read_text(encoding="utf-8")
        self.assertNotIn('hx-delete="{% url \'delete-ticket-document\'', source)
        self.assertIn('hx-post="{% url \'delete-ticket-document\'', source)
