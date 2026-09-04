"""Regression contracts for biometric device and user mutations."""

import ast
from pathlib import Path

from django.test import SimpleTestCase


class BiometricMutationSecurityContractTests(SimpleTestCase):
    backend_dir = Path(__file__).resolve().parent.parent

    @classmethod
    def _function_source(cls, function_name):
        path = cls.backend_dir / "biometric/views.py"
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

    def test_all_destructive_biometric_views_are_post_only(self):
        for function_name in (
            "biometric_device_archive",
            "biometric_device_delete",
            "biometric_device_unschedule",
            "biometric_device_live",
            "enable_cosec_face_recognition",
            "delete_biometric_user",
            "delete_horilla_cosec_user",
            "bio_users_bulk_delete",
            "cosec_users_bulk_delete",
            "delete_dahua_user",
            "delete_etimeoffice_user",
        ):
            with self.subTest(function=function_name):
                self.assertIn("@require_POST", self._function_source(function_name))

    def test_local_mutations_use_short_transactions_and_row_locks(self):
        for function_name in (
            "biometric_device_archive",
            "biometric_device_delete",
            "delete_biometric_user",
            "delete_horilla_cosec_user",
            "bio_users_bulk_delete",
            "cosec_users_bulk_delete",
            "delete_dahua_user",
            "delete_etimeoffice_user",
        ):
            with self.subTest(function=function_name):
                source = self._function_source(function_name)
                self.assertIn("transaction.atomic()", source)
                self.assertIn("select_for_update()", source)

    def test_device_user_deletes_are_tenant_and_device_scoped(self):
        source = (self.backend_dir / "biometric/views.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("def _visible_biometric_employees", source)
        self.assertIn("device_id__in=BiometricDevices.objects.all()", source)
        self.assertIn(".filter(uid=uid, device_id=device)", source)
        self.assertIn(".filter(user_id=user_id, device_id=device)", source)
        for machine_type in ("zk", "cosec", "dahua", "etimeoffice"):
            with self.subTest(machine_type=machine_type):
                self.assertIn(f'machine_type="{machine_type}"', source)

    def test_external_delete_succeeds_before_local_mapping_is_removed(self):
        zk_source = self._function_source("delete_biometric_user")
        self.assertLess(
            zk_source.index("conn.delete_user(uid=uid)"),
            zk_source.index("locked_mapping.delete()"),
        )
        self.assertIn("conn.disconnect()", zk_source)

        cosec_source = self._function_source("delete_horilla_cosec_user")
        self.assertLess(
            cosec_source.index("cosec.delete_cosec_user(user_id)"),
            cosec_source.index("locked_mapping.delete()"),
        )
        self.assertIn('response.get("Response-Code") == "0"', cosec_source)

    def test_dahua_delete_requires_employee_delete_permission(self):
        source = self._function_source("delete_dahua_user")
        self.assertIn(
            '@permission_required("biometric.delete_biometricemployees")', source
        )

    def test_templates_post_user_deletions_with_csrf(self):
        template_roots = (
            self.backend_dir / "biometric/templates",
            self.backend_dir / "horilla_theme/templates/biometric",
            self.backend_dir / "horilla_theme/templates/biometric_users",
        )
        combined = "\n".join(
            path.read_text(encoding="utf-8")
            for root in template_roots
            for path in root.rglob("*.html")
        )
        self.assertNotIn('href="{% url \'delete-biometric-user\'', combined)
        self.assertNotIn('href="{% url \'delete-cosec-user\'', combined)
        self.assertNotIn('hx-delete="{% url \'delete-dahua-user\'', combined)
        self.assertNotIn('hx-delete="{% url \'delete-etimeoffice-user\'', combined)
        self.assertIn('action="{% url \'delete-biometric-user\'', combined)
        self.assertIn('action="{% url \'delete-cosec-user\'', combined)
        self.assertIn("{% csrf_token %}", combined)

    def test_live_capture_and_scheduler_do_not_start_from_web_imports(self):
        views_source = (self.backend_dir / "biometric/views.py").read_text(
            encoding="utf-8"
        )
        cbv_source = (self.backend_dir / "biometric/cbv/biometric.py").read_text(
            encoding="utf-8"
        )
        for source in (views_source, cbv_source):
            self.assertNotIn("BackgroundScheduler", source)
            self.assertNotIn("scheduler.start()", source)

        scheduler_source = (self.backend_dir / "biometric/scheduler.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("def sync_biometric_jobs", scheduler_source)
        self.assertIn("max_instances=1", scheduler_source)
        self.assertIn("coalesce=True", scheduler_source)

    def test_live_capture_and_face_controls_post_from_templates(self):
        live_source = (
            self.backend_dir / "biometric/templates/biometric/live_capture.html"
        ).read_text(encoding="utf-8")
        self.assertIn('hx-post="{% url \'biometric-device-live-capture\' %}"', live_source)
        self.assertNotIn('hx-get="{% url \'biometric-device-live-capture\'', live_source)

        combined = "\n".join(
            path.read_text(encoding="utf-8")
            for root in (
                self.backend_dir / "biometric/templates/biometric",
                self.backend_dir / "horilla_theme/templates/biometric",
            )
            for path in root.rglob("*.html")
        )
        self.assertNotIn(
            'href="{% url \'enable-cosec-face-recognition\'', combined
        )
        self.assertIn(
            'action="{% url \'enable-cosec-face-recognition\'', combined
        )
