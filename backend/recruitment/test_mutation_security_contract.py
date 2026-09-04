"""Regression contracts for recruitment mutation endpoints."""

import ast
from pathlib import Path

from django.test import SimpleTestCase

from recruitment.views import views as recruitment_views


class RecruitmentMutationSecurityContractTests(SimpleTestCase):
    backend_dir = Path(__file__).resolve().parent.parent

    def _function_source(self, relative_path, function_name):
        module_source = (self.backend_dir / relative_path).read_text(encoding="utf-8")
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

    def test_recruitment_mutators_are_post_only(self):
        mutators = {
            "recruitment/views/actions.py": (
                "candidate_archive",
                "candidate_bulk_archive",
                "note_delete",
                "note_delete_individual",
                "remove_stage_manager",
            ),
            "recruitment/views/views.py": (
                "recruitment_archive",
                "recruitment_close_pipeline",
                "recruitment_reopen_pipeline",
                "change_candidate_stage",
                "update_candidate_stage_and_sequence",
                "update_candidate_sequence",
                "candidate_stage_update",
                "stage_title_update",
                "candidate_conversion",
                "candidate_sequence_update",
                "stage_sequence_update",
                "delete_stage_note_file",
                "delete_individual_note_file",
                "candidate_can_view_note",
                "candidate_schedule_date_update",
                "interview_employee_remove",
                "delete_profile_image",
                "interview_delete",
                "delete_resume_file",
                "document_approve",
                "skill_zone_delete",
                "skill_zone_archive",
                "skill_zone_cand_delete",
                "skill_zone_cand_archive",
                "update_candidate_rating",
                "candidate_self_tracking",
                "candidate_self_tracking_rating_option",
                "delete_reject_reason",
                "delete_skills",
                "document_delete",
                "delete_candidate_rejection",
            ),
            "recruitment/views/surveys.py": ("delete_template",),
        }

        for module_path, function_names in mutators.items():
            for function_name in function_names:
                with self.subTest(function=function_name):
                    source = self._function_source(module_path, function_name)
                    self.assertTrue(
                        '@require_http_methods(["POST"])' in source
                        or "@require_POST" in source
                    )

    def test_sequence_parser_validates_type_size_ids_and_unique_order(self):
        self.assertEqual(
            recruitment_views._parse_sequence_map('{"2": 0, "1": "1"}'),
            {2: 0, 1: 1},
        )
        invalid_values = (
            None,
            "[]",
            "{}",
            '{"0": 1}',
            '{"1": -1}',
            '{"x": 1}',
            '{"1": 1, "2": 1}',
        )
        for value in invalid_values:
            with self.subTest(value=value), self.assertRaises(ValueError):
                recruitment_views._parse_sequence_map(value)

    def test_pipeline_reorders_are_transactional_and_recruitment_scoped(self):
        for function_name in (
            "update_candidate_stage_and_sequence",
            "update_candidate_sequence",
            "candidate_stage_update",
            "candidate_sequence_update",
            "stage_sequence_update",
        ):
            with self.subTest(function=function_name):
                source = self._function_source(
                    "recruitment/views/views.py", function_name
                )
                self.assertIn("@transaction.atomic", source)
                self.assertIn("recruitment", source)

    def test_candidate_stage_mutations_use_exact_target_authorization(self):
        for function_name in (
            "change_candidate_stage",
            "update_candidate_stage_and_sequence",
            "update_candidate_sequence",
            "candidate_stage_update",
            "candidate_sequence_update",
        ):
            with self.subTest(function=function_name):
                source = self._function_source(
                    "recruitment/views/views.py", function_name
                )
                self.assertIn("_can_manage_recruitment(", source)
                self.assertIn('"recruitment.change_candidate"', source)

        bulk_source = self._function_source(
            "recruitment/views/views.py", "change_candidate_stage"
        )
        self.assertIn("_parse_posted_ids(", bulk_source)
        self.assertIn("Candidate.objects.select_for_update()", bulk_source)
        self.assertIn("len(candidates) != len(candidate_ids)", bulk_source)
        self.assertIn("Candidate.objects.bulk_update", bulk_source)
        self.assertNotIn("request.GET", bulk_source)

    def test_recruitment_and_stage_state_changes_lock_exact_targets(self):
        for function_name in (
            "recruitment_archive",
            "recruitment_close_pipeline",
            "recruitment_reopen_pipeline",
        ):
            with self.subTest(function=function_name):
                source = self._function_source(
                    "recruitment/views/views.py", function_name
                )
                self.assertIn("@transaction.atomic", source)
                self.assertIn("select_for_update()", source)

        for function_name in (
            "recruitment_close_pipeline",
            "recruitment_reopen_pipeline",
            "stage_sequence_update",
            "update_stage_order",
        ):
            with self.subTest(function=function_name):
                source = self._function_source(
                    "recruitment/views/views.py", function_name
                )
                self.assertIn("_can_manage_recruitment(", source)

        stage_order = self._function_source(
            "recruitment/views/views.py", "update_stage_order"
        )
        self.assertIn("with transaction.atomic():", stage_order)
        self.assertIn("Stage.objects.select_for_update()", stage_order)
        self.assertIn("len(stages) != len(stage_ids)", stage_order)

    def test_talent_pool_mutations_are_transactional(self):
        for function_name in ("skill_zone_delete", "skill_zone_archive"):
            with self.subTest(function=function_name):
                source = self._function_source(
                    "recruitment/views/views.py", function_name
                )
                self.assertIn("@transaction.atomic", source)
                self.assertIn("select_for_update()", source)

        archive = self._function_source(
            "recruitment/views/views.py", "skill_zone_archive"
        )
        self.assertIn(".update(is_active=new_state)", archive)

        for function_name in ("skill_zone_cand_archive", "skill_zone_cand_delete"):
            with self.subTest(function=function_name):
                source = self._function_source(
                    "recruitment/views/views.py", function_name
                )
                self.assertIn("@transaction.atomic", source)
                self.assertIn("select_for_update()", source)

    def test_candidate_notes_interviews_and_profile_are_target_scoped(self):
        for function_name in (
            "delete_stage_note_file",
            "delete_individual_note_file",
            "candidate_can_view_note",
            "stage_title_update",
            "interview_employee_remove",
            "interview_delete",
            "delete_profile_image",
        ):
            with self.subTest(function=function_name):
                source = self._function_source(
                    "recruitment/views/views.py", function_name
                )
                self.assertIn("@transaction.atomic", source)
                self.assertIn("select_for_update()", source)
                self.assertIn("_can_manage_recruitment(", source)

        profile = self._function_source(
            "recruitment/views/views.py", "delete_profile_image"
        )
        self.assertIn("transaction.on_commit(", profile)
        self.assertNotIn("os.remove(", profile)

    def test_rating_skill_and_resume_mutations_validate_before_writing(self):
        rating = self._function_source(
            "recruitment/views/views.py", "update_candidate_rating"
        )
        self.assertIn("@transaction.atomic", rating)
        self.assertIn("rating < 0 or rating > 5", rating)
        self.assertIn("CandidateRating.objects.select_for_update()", rating)

        skills = self._function_source(
            "recruitment/views/views.py", "delete_skills"
        )
        self.assertIn('@permission_required("recruitment.delete_skill")', skills)
        self.assertIn("@transaction.atomic", skills)
        self.assertIn("_parse_posted_ids(", skills)
        self.assertIn("len(skills) != len(ids)", skills)

        resumes = self._function_source(
            "recruitment/views/views.py", "delete_resume_file"
        )
        self.assertIn("@transaction.atomic", resumes)
        self.assertIn("_parse_posted_ids(", resumes)
        self.assertIn("_can_manage_recruitment(", resumes)
        self.assertIn("resumes.count() != len(ids)", resumes)

    def test_candidate_bulk_archive_posts_state_and_is_all_or_nothing(self):
        source = self._function_source(
            "recruitment/views/actions.py", "candidate_bulk_archive"
        )
        self.assertIn("@transaction.atomic", source)
        self.assertIn('request.POST.get("is_active"', source)
        self.assertNotIn("request.GET", source)
        self.assertIn("Candidate.objects.select_for_update()", source)
        self.assertIn("candidates.count() != len(ids)", source)

        scripts = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (
                self.backend_dir / "recruitment/static/candidate/bulk.js",
                self.backend_dir
                / "recruitment/templates/cbv/candidates/candidates.html",
            )
        )
        self.assertNotIn("candidate-bulk-archive/?is_active=", scripts)
        self.assertGreaterEqual(scripts.count('is_active: "False"'), 2)
        self.assertGreaterEqual(scripts.count('is_active: "True"'), 2)

    def test_recruitment_delete_actions_are_atomic_and_locked(self):
        for function_name in (
            "recruitment_delete",
            "recruitment_delete_pipeline",
            "note_delete",
            "note_delete_individual",
            "stage_delete",
            "candidate_delete",
            "candidate_bulk_delete",
            "candidate_archive",
            "remove_stage_manager",
            "remove_recruitment_manager",
        ):
            with self.subTest(function=function_name):
                source = self._function_source(
                    "recruitment/views/actions.py", function_name
                )
                self.assertIn("@transaction.atomic", source)
                self.assertIn("select_for_update()", source)

        bulk_delete = self._function_source(
            "recruitment/views/actions.py", "candidate_bulk_delete"
        )
        self.assertIn("_parse_posted_ids(", bulk_delete)
        self.assertIn("candidates.count() != len(ids)", bulk_delete)
        self.assertIn("transaction.set_rollback(True)", bulk_delete)

        for function_name in (
            "note_delete",
            "note_delete_individual",
            "stage_delete",
            "remove_stage_manager",
            "remove_recruitment_manager",
        ):
            with self.subTest(scope=function_name):
                source = self._function_source(
                    "recruitment/views/actions.py", function_name
                )
                self.assertIn("_can_manage_recruitment(", source)

    def test_linkedin_cleanup_runs_only_after_recruitment_commit(self):
        deletion = self._function_source(
            "recruitment/views/actions.py", "recruitment_delete"
        )
        self.assertIn("transaction.on_commit(", deletion)
        self.assertIn("persist=False", deletion)

        linkedin = self._function_source(
            "recruitment/views/linkedin.py", "delete_post"
        )
        self.assertIn("timeout=10", linkedin)
        self.assertIn("except requests.RequestException", linkedin)
        self.assertIn("if persist:", linkedin)
        self.assertNotIn("recruitment.save()", linkedin)

    def test_all_linkedin_http_calls_have_timeouts(self):
        linkedin = (self.backend_dir / "recruitment/views/linkedin.py").read_text(
            encoding="utf-8"
        )
        model_source = (self.backend_dir / "recruitment/models.py").read_text(
            encoding="utf-8"
        )
        for source in (linkedin, model_source):
            calls = (
                source.count("requests.get(")
                + source.count("requests.post(")
                + source.count("requests.delete(")
            )
            self.assertEqual(calls, source.count("timeout=10"))

    def test_candidate_portal_note_deletes_are_scoped_to_session_candidate(self):
        actions_source = self._function_source(
            "recruitment/views/actions.py", "note_delete_individual"
        )
        file_source = self._function_source(
            "recruitment/views/views.py", "delete_individual_note_file"
        )
        for source in (actions_source, file_source):
            self.assertIn('request.session.get("candidate_id")', source)
            self.assertIn("note.candidate_id_id", source)
            self.assertIn('status=404', source)

    def test_templates_never_use_get_for_recruitment_mutations(self):
        template_roots = (
            self.backend_dir / "recruitment/templates",
            self.backend_dir / "horilla_theme/templates",
            self.backend_dir / "employee/templates",
        )
        combined = "\n".join(
            path.read_text(encoding="utf-8")
            for root in template_roots
            for path in root.rglob("*.html")
        )
        unsafe_fragments = (
            'hx-get="{% url \'rec-candidate-archive\'',
            'href="{% url \'rec-candidate-archive\'',
            'hx-get="{% url \'recruitment-archive\'',
            'href="{% url \'recruitment-archive\'',
            'hx-get="{% url \'note-delete\'',
            'hx-get="{% url \'note-delete-individual\'',
            'hx-get="{% url \'delete-stage-note-file\'',
            'hx-get="{% url \'delete-individual-note-file\'',
            'hx-get="{% url \'delete-interview\'',
            'hx-get="{% url \'delete-resume-file\'',
            'hx-get="{% url \'candidate-document-approve\'',
            'href="{% url \'delete-profile-image\'',
            'href="{% url \'candidate-conversion\'',
            'href="{% url \'recruitment-close-pipeline\'',
            'href="{% url \'recruitment-reopen-pipeline\'',
            'href="{% url \'skill-zone-archive\'',
            'href="{% url \'skill-zone-delete\'',
            'href="{% url \'delete-skills\'',
            'href="{% url \'delete-reject-reasons\'',
            'hx-get="{% url \'candidate-self-tracking\'',
            'hx-get="{% url \'candidate-self-tracking-rating-option\'',
            'href="{% url \'survey-template-delete\'',
            'href="{% url \'recruitment-survey-question-template-delete\'',
        )
        for fragment in unsafe_fragments:
            with self.subTest(fragment=fragment):
                self.assertNotIn(fragment, combined)

        interview_delete = self._function_source(
            "recruitment/views/views.py", "interview_delete"
        )
        self.assertIn("@transaction.atomic", interview_delete)
        self.assertIn("select_for_update()", interview_delete)

        rejection_source = (
            self.backend_dir / "recruitment/cbv/candidates.py"
        ).read_text(encoding="utf-8")
        self.assertIn("self.target_candidate = candidates.filter", rejection_source)
        self.assertIn('data["candidate_id"] = self.target_candidate.id', rejection_source)
        self.assertIn("RejectedCandidate.objects.select_for_update()", rejection_source)

        pipeline = (
            self.backend_dir
            / "recruitment/templates/cbv/pipeline/pipeline.html"
        ).read_text(encoding="utf-8")
        self.assertIn('type: "POST"', pipeline)
        self.assertNotIn("window.location.href = url", pipeline)

    def test_candidate_documents_are_portal_and_recruitment_scoped(self):
        module_path = "recruitment/views/views.py"
        helper = self._function_source(
            module_path, "_candidate_documents_for_request"
        )
        self.assertIn('request.session.get("candidate_id")', helper)
        self.assertIn("candidate_id_id=session_candidate_id", helper)
        self.assertIn("recruitment_managers=employee", helper)
        self.assertIn("stage_managers=employee", helper)

        for function_name in ("file_upload", "view_file"):
            with self.subTest(function=function_name):
                source = self._function_source(module_path, function_name)
                self.assertIn("_candidate_documents_for_request(request", source)

        for function_name in (
            "update_document_title",
            "document_delete",
            "document_approve",
        ):
            with self.subTest(function=function_name):
                source = self._function_source(module_path, function_name)
                self.assertIn("select_for_update()", source)
                self.assertIn("@transaction.atomic", source)

        upload = self._function_source(module_path, "file_upload")
        self.assertIn("with transaction.atomic():", upload)
        self.assertIn('document_item.status = "requested"', upload)
        self.assertIn("document_item.reject_reason = None", upload)

        reject = self._function_source(module_path, "document_reject")
        self.assertIn('@require_http_methods(["GET", "POST"])', reject)
        self.assertIn("with transaction.atomic():", reject)
        self.assertIn("select_for_update()", reject)

        model_source = (
            self.backend_dir / "recruitment/models.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            'related_company_field="candidate_id__recruitment_id__company_id"',
            model_source,
        )

    def test_survey_question_delete_is_post_only_atomic_and_tenant_scoped(self):
        source = self._function_source(
            "recruitment/views/surveys.py", "delete_survey_question"
        )
        self.assertIn("@require_POST", source)
        self.assertIn("@transaction.atomic", source)
        self.assertIn("RecruitmentSurvey.objects.select_for_update()", source)

    def test_survey_order_and_template_delete_are_atomic(self):
        order = self._function_source(
            "recruitment/views/surveys.py", "question_order_update"
        )
        self.assertIn("@require_POST", order)
        self.assertIn("@transaction.atomic", order)
        self.assertIn("RecruitmentSurvey.objects.select_for_update()", order)
        self.assertIn("_can_manage_recruitment(", order)
        self.assertIn("RecruitmentSurvey.objects.bulk_update", order)

        template_delete = self._function_source(
            "recruitment/views/surveys.py", "delete_template"
        )
        self.assertIn("@transaction.atomic", template_delete)
        self.assertIn("SurveyTemplate.objects.select_for_update()", template_delete)
        self.assertIn("transaction.set_rollback(True)", template_delete)

    def test_recruitment_manager_decorator_honors_requested_permission(self):
        source = self._function_source("horilla/decorators.py", "is_recruitment_manager")
        self.assertNotIn('perm = "recruitment.view_recruitmentsurvey"', source)
        self.assertIn("user.has_perm(perm)", source)
        self.assertIn("Recruitment.objects.filter(", source)
        self.assertNotIn("for i in recs", source)
