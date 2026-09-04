"""Regression contracts for onboarding mutation endpoints."""

import ast
import inspect
from pathlib import Path

from django.test import SimpleTestCase
from django.urls import reverse

from onboarding import views
from onboarding.cbv.pipeline import AssignTask


class MutationSecurityContractTests(SimpleTestCase):
    def _source(self, function_name):
        module_source = Path(views.__file__).read_text(encoding="utf-8")
        module_lines = module_source.splitlines(keepends=True)
        functions = {
            node.name: node
            for node in ast.parse(module_source).body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        node = functions[function_name]
        first_line = min(
            [node.lineno] + [decorator.lineno for decorator in node.decorator_list]
        )
        return "".join(module_lines[first_line - 1 : node.end_lineno])

    def test_json_id_parser_normalizes_and_rejects_unsafe_input(self):
        self.assertEqual(views._parse_json_id_list('["2", 1, 2]'), [2, 1])

        invalid_values = (None, "not-json", "{}", "[0]", "[-1]", '["x"]')
        for value in invalid_values:
            with self.subTest(value=value), self.assertRaises(ValueError):
                views._parse_json_id_list(value)

        with self.assertRaises(ValueError):
            views._parse_json_id_list(str(list(range(1, 502))))

    def test_legacy_mutators_are_post_only_and_do_not_read_query_parameters(self):
        mutator_names = (
            "stage_delete",
            "task_delete",
            "candidate_delete",
            "candidate_stage_update",
            "candidate_stage_bulk_update",
            "candidate_task_bulk_update",
            "candidate_sequence_update",
            "stage_sequence_update",
            "change_task_status",
            "update_offer_letter_status",
            "offer_letter_bulk_status_update",
            "onboarding_candidate_bulk_delete",
            "assign_task",
            "undo_rejected_candidate",
        )
        module_source = Path(views.__file__).read_text(encoding="utf-8")
        module_lines = module_source.splitlines(keepends=True)
        functions = {
            node.name: node
            for node in ast.parse(module_source).body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }

        for mutator_name in mutator_names:
            with self.subTest(mutator=mutator_name):
                node = functions[mutator_name]
                first_line = min(
                    [node.lineno]
                    + [decorator.lineno for decorator in node.decorator_list]
                )
                source = "".join(module_lines[first_line - 1 : node.end_lineno])
                self.assertRegex(
                    source, r"@require_(?:POST|http_methods\(\[\"POST\"\]\))"
                )
                self.assertNotIn("request.GET", source)

    def test_onboarding_bulk_and_status_updates_lock_and_scope_rows(self):
        module_source = Path(views.__file__).read_text(encoding="utf-8")
        module_lines = module_source.splitlines(keepends=True)
        functions = {
            node.name: node
            for node in ast.parse(module_source).body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }

        for name in (
            "candidate_task_update",
            "candidate_stage_update",
            "candidate_stage_bulk_update",
            "candidate_task_bulk_update",
            "change_task_status",
            "update_offer_letter_status",
            "offer_letter_bulk_status_update",
            "onboarding_candidate_bulk_delete",
            "undo_rejected_candidate",
        ):
            with self.subTest(function=name):
                node = functions[name]
                first_line = min(
                    [node.lineno]
                    + [decorator.lineno for decorator in node.decorator_list]
                )
                source = "".join(module_lines[first_line - 1 : node.end_lineno])
                self.assertIn("@transaction.atomic", source)
                self.assertIn("select_for_update()", source)

        for name in (
            "candidate_task_update",
            "assign_task",
            "candidate_stage_update",
            "candidate_stage_bulk_update",
            "candidate_task_bulk_update",
            "change_task_status",
        ):
            node = functions[name]
            source = "".join(module_lines[node.lineno - 1 : node.end_lineno])
            self.assertRegex(source, r"_can_manage_(?:task|stage)")

        delete_source = "".join(
            module_lines[
                functions["onboarding_candidate_bulk_delete"].lineno
                - 1 : functions["onboarding_candidate_bulk_delete"].end_lineno
            ]
        )
        self.assertIn("transaction.set_rollback(True)", delete_source)

    def test_stage_order_routes_have_distinct_names(self):
        self.assertEqual(
            reverse("onboarding-stage-order", kwargs={"pk": 7}),
            "/onboarding/onboarding-stage-sequence-update/7/",
        )
        self.assertEqual(
            reverse("onboarding-stage-sequence-update"),
            "/onboarding/stage-sequence-update/",
        )

    def test_pipeline_assignment_has_no_get_mutation_handler(self):
        self.assertNotIn("get", AssignTask.__dict__)
        source = inspect.getsource(AssignTask.post)
        self.assertIn("@transaction.atomic", source)
        self.assertIn("Task assignment scope is invalid.", source)
        self.assertIn("valid_statuses", source)

    def test_templates_use_post_for_onboarding_mutations(self):
        backend_dir = Path(__file__).resolve().parent.parent
        template_paths = (
            "onboarding/templates/onboarding/candidates.html",
            "onboarding/templates/onboarding/group_by.html",
            "onboarding/templates/onboarding/kanban/kanban.html",
            "onboarding/templates/onboarding/onboarding_table.html",
            "onboarding/templates/onboarding/candidate_task.html",
            "onboarding/templates/onboarding/candidates_view.html",
            "onboarding/templates/onboarding/dashboard/status_list.html",
            "onboarding/templates/cbv/dashboard/status.html",
            "onboarding/templates/cbv/onboarding_candidates/actions.html",
            "onboarding/templates/cbv/onboarding_candidates/offer_letter.html",
            "onboarding/templates/cbv/pipeline/onboarding/tasks.html",
            "recruitment/templates/cbv/candidates/profile_onboarding_tab.html",
            "recruitment/templates/candidate/individual.html",
        )
        combined = "\n".join(
            (backend_dir / relative_path).read_text(encoding="utf-8")
            for relative_path in template_paths
        )

        unsafe_fragments = (
            'hx-get="{% url \'change-task-status\'',
            'hx-get="{% url \'update-offer-letter-status\'',
            'hx-get="{% url \'assign-task\'',
            'hx-get="{% url \'assign-task-pipeline\'',
            'href="{% url \'candidate-delete\'',
            'href="{% url \'stage-delete\'',
            'href="{% url \'task-delete\'',
        )
        for fragment in unsafe_fragments:
            with self.subTest(fragment=fragment):
                self.assertNotIn(fragment, combined)

        candidates_view = (
            backend_dir / "onboarding/templates/onboarding/candidates_view.html"
        ).read_text(encoding="utf-8")
        self.assertIn('type: "POST"', candidates_view)
        self.assertIn('csrfmiddlewaretoken: "{{ csrf_token }}"', candidates_view)

    def test_stage_task_and_candidate_deletes_are_atomic_and_scoped(self):
        for function_name in ("stage_delete", "task_delete", "candidate_delete"):
            with self.subTest(function=function_name):
                source = self._source(function_name)
                self.assertIn("@transaction.atomic", source)
                self.assertIn("select_for_update()", source)
                self.assertIn("transaction.set_rollback(True)", source)

        self.assertIn("_can_manage_recruitment(", self._source("stage_delete"))
        self.assertIn("_can_manage_task(", self._source("task_delete"))
        self.assertNotIn(
            '@permission_required("onboarding.delete_onboardingstage")',
            self._source("stage_delete"),
        )
        self.assertNotIn(
            '@permission_required("onboarding.delete_onboardingtask")',
            self._source("task_delete"),
        )

    def test_sequence_updates_lock_validate_and_bulk_write(self):
        self.assertEqual(views._parse_sequence_map('{"2": 0, "1": "1"}'), {2: 0, 1: 1})
        for value in (None, "[]", "{}", '{"0": 1}', '{"1": -1}', '{"1": 0, "2": 0}'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                views._parse_sequence_map(value)

        candidate_source = self._source("candidate_sequence_update")
        self.assertIn("CandidateStage.objects.select_for_update()", candidate_source)
        self.assertIn("len(candidate_stages) != len(sequence_data)", candidate_source)
        self.assertIn("_can_manage_stage(", candidate_source)
        self.assertIn("CandidateStage.objects.bulk_update", candidate_source)

        stage_source = self._source("stage_sequence_update")
        self.assertIn("OnboardingStage.objects.select_for_update()", stage_source)
        self.assertIn("len(stages) != len(sequence_data)", stage_source)
        self.assertIn("_can_manage_recruitment(", stage_source)
        self.assertIn("OnboardingStage.objects.bulk_update", stage_source)

    def test_task_forms_sync_candidate_tasks_transactionally(self):
        create_source = self._source("task_creation")
        update_source = self._source("task_update")
        for source in (create_source, update_source):
            self.assertIn("@transaction.atomic", source)
            self.assertIn("Task assignment scope is invalid.", source)
            self.assertIn("CandidateTask.objects.bulk_create", source)
            self.assertIn("_notify_after_commit(", source)

        self.assertIn("OnboardingTask.objects.select_for_update()", update_source)
        self.assertIn("CandidateTask.objects.select_for_update()", update_source)
        self.assertIn("CandidateTask.objects.bulk_update", update_source)

    def test_joining_probation_and_stage_title_updates_are_validated(self):
        joining = self._source("update_joining")
        self.assertIn('@permission_required("recruitment.change_candidate")', joining)
        self.assertNotIn('candidate.change_candidate', joining)
        self.assertIn("@transaction.atomic", joining)
        self.assertIn("date.fromisoformat", joining)
        self.assertIn("Candidate.objects.select_for_update()", joining)
        self.assertIn("onboarding_stage__isnull=False", joining)

        for function_name in ("stage_name_update", "update_probation_end"):
            source = self._source(function_name)
            self.assertIn("@transaction.atomic", source)
            self.assertIn("select_for_update()", source)
            self.assertIn("_can_manage_stage(", source)
