from __future__ import annotations

import csv
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class FinalProcurementSourceTests(unittest.TestCase):
    def test_permission_remove_does_not_ignore_route_ids(self):
        source = (ROOT / "backend/base/views.py").read_text(encoding="utf-8")
        block = source.split("def user_group_permission_remove", 1)[1].split("def _next_role_copy_name", 1)[0]
        self.assertIn("id=gid", block)
        self.assertIn("id=pid", block)
        self.assertNotIn("Group.objects.get(id=1)", block)
        self.assertNotIn("Permission.objects.get(id=2)", block)

    def test_role_copy_does_not_copy_members_or_company_scope(self):
        source = (ROOT / "backend/base/views.py").read_text(encoding="utf-8")
        block = source.split("def user_group_permission_copy", 1)[1].split("def group_remove_user", 1)[0]
        self.assertIn("copied.permissions.set(source.permissions.all())", block)
        self.assertNotIn("copied.user_set", block)
        self.assertNotIn("CompanyGroupAssignment.objects.create", block)
        self.assertIn("data_scopes_copied=false", block)

    def test_permission_ui_uses_app_qualified_refs(self):
        theme = (ROOT / "backend/horilla_theme/templates/base/auth/permission_table.html").read_text(encoding="utf-8")
        refs = (ROOT / "backend/base/permission_refs.py").read_text(encoding="utf-8")
        self.assertIn("{{ perm.app_label }}.add_{{ model.model_name }}", theme)
        self.assertIn("content_type__app_label", refs)
        self.assertIn("ambiguous", refs)

    def test_initialization_snapshot_source_excludes_secrets(self):
        source = (ROOT / "backend/base/management/commands/export_school_initialization_snapshot.py").read_text(encoding="utf-8")
        self.assertIn('"containsPasswords": False', source)
        self.assertIn('"containsTokens": False', source)
        self.assertIn('"containsEncryptionKeys": False', source)
        self.assertNotIn('"SECRET_KEY",', source)
        self.assertNotIn('"MYSQL_PASSWORD",', source)
        self.assertNotIn('"FIELD_ENCRYPTION_KEYS",', source)


class FinalEvidenceBuilderTests(unittest.TestCase):
    def _write_json(self, path: Path, payload: dict):
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def _evidence(self, root: Path):
        required_phases = [
            "release",
            "django-check-deploy",
            "migration-drift",
            "migration-applied",
            "field-security-check",
            "hr01-hr18-tests",
            "bootstrap-first-admin",
            "school-initialization-snapshot",
            "backup-create",
            "backup-verify",
            "backup-restore",
            "restored-migration-check",
            "handover-create",
            "handover-verify",
            "handover-restore",
            "handover-restored-migration-check",
            "ready-endpoint",
        ]
        runtime = root / "runtime.json"
        self._write_json(
            runtime,
            {
                "status": "PASSED",
                "productionTouched": False,
                "gitHubTouched": False,
                "phases": [{"name": name, "status": "PASSED"} for name in required_phases],
            },
        )
        init = root / "init.json"
        self._write_json(
            init,
            {
                "kind": "YUEKE_UNIVERSITY_HR_SCHOOL_INITIALIZATION_SNAPSHOT",
                "secretPolicy": {
                    "containsPasswords": False,
                    "containsTokens": False,
                    "containsEncryptionKeys": False,
                },
                "roles": [],
                "migrations": [],
            },
        )
        perf = root / "perf.json"
        self._write_json(
            perf,
            {
                "status": "PASS",
                "concurrency": 100,
                "thresholds": {"normalMs": 3000, "analyticsMs": 5000},
                "targets": [
                    {"category": "NORMAL", "pass": True},
                    {"category": "ANALYTICS", "pass": True},
                ],
            },
        )
        trial = root / "trial.json"
        self._write_json(
            trial,
            {
                "status": "PASS",
                "buyerConfirmed": True,
                "supplierConfirmed": True,
                "buyerRepresentative": "学校代表",
                "supplierRepresentative": "跃科代表",
                "startAt": "2026-09-17T09:00:00+08:00",
                "endAt": "2026-09-17T17:00:00+08:00",
                "sampledFlows": [{"flowCode": "HR03", "status": "PASS"}],
            },
        )
        training = root / "training.csv"
        with training.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["participant", "role", "session_at", "trainer", "topic", "attendance_status", "acknowledgement", "evidence_ref"])
            w.writeheader()
            w.writerow({"participant": "A", "role": "ADMIN", "session_at": "2026-09-17T09:00:00+08:00", "trainer": "T", "topic": "admin", "attendance_status": "COMPLETED", "acknowledgement": "CONFIRMED", "evidence_ref": "a"})
            w.writerow({"participant": "B", "role": "OPERATOR", "session_at": "2026-09-17T14:00:00+08:00", "trainer": "T", "topic": "ops", "attendance_status": "COMPLETED", "acknowledgement": "CONFIRMED", "evidence_ref": "b"})
        remediation = root / "remediation.csv"
        with remediation.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["issue_id", "severity", "description", "status", "resolution", "verification_status", "school_acceptance", "evidence_ref"])
            w.writeheader()
            w.writerow({"issue_id": "NO_ISSUES", "severity": "INFO", "description": "no open issues", "status": "CLOSED", "resolution": "confirmed", "verification_status": "PASS", "school_acceptance": "ACCEPTED", "evidence_ref": "x"})
        external = root / "external.json"
        self._write_json(
            external,
            {
                "integrations": [
                    {
                        "integrationCode": "SCHOOL_SSO",
                        "applicability": "REQUIRED",
                        "status": "PASS",
                        "buyerConfirmed": True,
                        "supplierConfirmed": True,
                    }
                ]
            },
        )
        return runtime, init, perf, trial, remediation, training, external

    def _run_builder(self, root: Path, output: Path, *, mutate=None):
        runtime, init, perf, trial, remediation, training, external = self._evidence(root)
        paths = {
            "runtime": runtime,
            "init": init,
            "perf": perf,
            "trial": trial,
            "remediation": remediation,
            "training": training,
            "external": external,
        }
        if mutate:
            mutate(paths)
        return subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/build_procurement_acceptance_package.py"),
                "--runtime-evidence", str(runtime),
                "--initialization-snapshot", str(init),
                "--performance-evidence", str(perf),
                "--trial-run-record", str(trial),
                "--remediation-register", str(remediation),
                "--training-record", str(training),
                "--external-integration-record", str(external),
                "--output", str(output),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )

    def test_complete_evidence_emits_release_certificate(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            output = root / "final.zip"
            result = self._run_builder(root, output)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            with zipfile.ZipFile(output) as zf:
                names = set(zf.namelist())
                self.assertIn("release_certificate.json", names)
                summary = json.loads(zf.read("acceptance_summary.json"))
            self.assertEqual(summary["status"], "COMPLETE")
            self.assertTrue(summary["releaseCertificate"])
            self.assertTrue(output.with_suffix(".zip.sha256").is_file())

    def test_performance_below_100_is_rejected_and_gets_no_certificate(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            output = root / "final.zip"
            def mutate(paths):
                data = json.loads(paths["perf"].read_text(encoding="utf-8"))
                data["concurrency"] = 99
                paths["perf"].write_text(json.dumps(data), encoding="utf-8")
            result = self._run_builder(root, output, mutate=mutate)
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue(output.is_file())
            with zipfile.ZipFile(output) as zf:
                self.assertNotIn("release_certificate.json", set(zf.namelist()))
                summary = json.loads(zf.read("acceptance_summary.json"))
            self.assertEqual(summary["status"], "INCOMPLETE")
            self.assertFalse(summary["releaseCertificate"])

    def test_unsigned_trial_run_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            output = root / "final.zip"
            def mutate(paths):
                data = json.loads(paths["trial"].read_text(encoding="utf-8"))
                data["buyerConfirmed"] = False
                paths["trial"].write_text(json.dumps(data), encoding="utf-8")
            result = self._run_builder(root, output, mutate=mutate)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("trialRun", result.stdout)


if __name__ == "__main__":
    unittest.main()
