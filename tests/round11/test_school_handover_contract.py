import importlib.util
import io
import json
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def text(rel):
    return (ROOT / rel).read_text(encoding="utf-8-sig")


def load_helper():
    path = ROOT / "backend/horilla_backup/handover.py"
    spec = importlib.util.spec_from_file_location("round11_handover_helper", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class SchoolHandoverPureContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.handover = load_helper()

    def test_archive_path_traversal_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            archive_path = Path(folder) / "bad.tar.gz"
            with tarfile.open(archive_path, "w:gz") as archive:
                info = tarfile.TarInfo("../escape.txt")
                payload = b"escape"
                info.size = len(payload)
                archive.addfile(info, io.BytesIO(payload))
            with self.assertRaises(self.handover.SchoolHandoverError):
                self.handover.inspect_archive(archive_path)

    def test_dump_row_count_evidence_is_bound_to_exported_sql(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            dump = root / "database.sql"
            dump.write_text(
                "INSERT INTO `alpha` (`id`) VALUES (1);\n"
                "INSERT INTO `alpha` (`id`) VALUES (2);\n"
                "INSERT INTO `beta` (`id`) VALUES (1);\n",
                encoding="utf-8",
            )
            stats = self.handover.write_dump_row_counts(
                dump, root / "counts.csv", root / "counts.json"
            )
            self.assertEqual(stats["row_count_table_count"], 2)
            self.assertEqual(stats["row_count_total_rows"], 3)
            rows = json.loads((root / "counts.json").read_text(encoding="utf-8"))
            self.assertEqual(rows, [
                {"table_name": "alpha", "row_count": 2},
                {"table_name": "beta", "row_count": 1},
            ])

    def test_detached_checksum_is_required_and_must_match(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            package = root / "school-handover-test.tar.gz"
            package.write_bytes(b"package-bytes")
            with self.assertRaises(self.handover.SchoolHandoverError):
                self.handover.verify_detached_checksum(package)

            digest = self.handover.sha256_file(package)
            checksum = root / "school-handover-test.tar.gz.sha256"
            checksum.write_text(f"{digest}  {package.name}\n", encoding="utf-8")
            self.assertEqual(self.handover.verify_detached_checksum(package), digest)

            package.write_bytes(b"tampered")
            with self.assertRaises(self.handover.SchoolHandoverError):
                self.handover.verify_detached_checksum(package)

    def test_archive_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            archive_path = Path(folder) / "bad-link.tar.gz"
            with tarfile.open(archive_path, "w:gz") as archive:
                info = tarfile.TarInfo("link")
                info.type = tarfile.SYMTYPE
                info.linkname = "/etc/passwd"
                archive.addfile(info)
            with self.assertRaises(self.handover.SchoolHandoverError):
                self.handover.inspect_archive(archive_path)

    def test_manifest_rejects_modified_or_unmanifested_artifacts(self):
        required = {
            "database.sql": b"CREATE TABLE x(id int);\n",
            "schema_dictionary.csv": b"table_name,column_name\n",
            "schema_dictionary.json": b"[]\n",
            "table_row_counts.csv": b"table_name,row_count\n",
            "table_row_counts.json": b"[]\n",
            "migration_state.json": b"[]\n",
            "api_route_inventory.csv": b"route,name,view\n",
            "configuration_catalog.csv": b"table_name,category,row_count,content_location\n",
            "configuration_catalog.json": b"[]\n",
            "interface_mapping_catalog.json": b"[]\n",
            "runtime_configuration.json": b"{}\n",
            "secret_handover_requirements.json": b"{}\n",
            "README-HANDOVER.txt": b"handover\n",
        }
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            media = root / "media.tar.gz"
            with tarfile.open(media, "w:gz"):
                pass
            required["media.tar.gz"] = media.read_bytes()
            artifacts = {}
            for name, payload in required.items():
                path = root / name
                path.write_bytes(payload)
                artifacts[name] = self.handover.artifact_metadata(path)
            (root / "manifest.json").write_text(
                json.dumps(
                    {
                        "format": self.handover.HANDOVER_FORMAT,
                        "artifacts": artifacts,
                    }
                ),
                encoding="utf-8",
            )
            self.handover.load_and_verify_manifest(root)
            (root / "database.sql").write_text("tampered", encoding="utf-8")
            with self.assertRaises(self.handover.SchoolHandoverError):
                self.handover.load_and_verify_manifest(root)

            (root / "database.sql").write_bytes(required["database.sql"])
            (root / "unexpected.txt").write_text("not in manifest", encoding="utf-8")
            with self.assertRaises(self.handover.SchoolHandoverError):
                self.handover.load_and_verify_manifest(root)

    def test_receipts_append_instead_of_rewriting_history(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = self.handover.append_receipt(root, {"event": "CREATED", "n": 1})
            self.handover.append_receipt(root, {"event": "VERIFIED", "n": 2})
            rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual([row["event"] for row in rows], ["CREATED", "VERIFIED"])
            self.assertEqual([row["n"] for row in rows], [1, 2])

    def test_static_gate_is_green(self):
        completed = subprocess.run(
            [sys.executable, str(ROOT / "scripts/check_school_handover_contract.py")],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["passed"], payload["total"])

    def test_restore_contract_preflights_media_before_database(self):
        source = text("backend/horilla_backup/management/commands/restore_school_handover_package.py")
        handle_start = source.index("    def handle(")
        handle_end = source.index("    @staticmethod\n    def _validate_media_target", handle_start)
        block = source[handle_start:handle_end]
        self.assertLess(block.index("_prepare_media_archive("), block.index("_restore_database("))
        self.assertIn("Refusing to restore over the live configured database", block)
        self.assertIn("_require_empty_database(", block)
        self.assertIn("_post_restore_check(", block)
        self.assertIn("table_row_counts.json", source)
        self.assertIn("post-restore exact row-count mismatch", source)

    def test_runtime_secret_values_are_not_written_to_handover_metadata(self):
        helper = text("backend/horilla_backup/handover.py")
        create = text("backend/horilla_backup/management/commands/create_school_handover_package.py")
        self.assertIn('"secrets_included": False', helper)
        self.assertIn('"contains_secret_values": False', helper)
        self.assertIn('"configured_key_ids"', helper)
        self.assertNotIn('database.get("PASSWORD")', helper)
        self.assertNotIn("PRODUCTION_BACKUP_ENCRYPTION_KEY", create)

    def test_acceptance_plan_includes_real_handover_create_verify_restore(self):
        completed = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/run_hr_acceptance_gate.py"),
                "--plan",
                "--project",
                "yueke_hr_acceptance_round11",
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
        output = completed.stdout
        self.assertIn("open-format school handover package", output)
        self.assertIn("renshi_handover_restore_test", output)
        source = text("scripts/run_hr_acceptance_gate.py")
        self.assertIn('"HANDOVER_STORAGE_PATH"', source)
        self.assertIn('"HANDOVER_AUDIT_STORAGE_PATH"', source)
        self.assertIn('"handover-create"', source)
        self.assertIn('"handover-verify"', source)
        self.assertIn("handover verify SHA-256 does not match the created package digest", source)
        self.assertIn('"handover-restore"', source)
        self.assertIn('evidence["handoverSha256"]', source)
        self.assertIn('evidence["handoverSchemaTableCounts"]', source)

    def test_compose_mounts_handover_and_audit_separately(self):
        compose = text("docker-compose.prod.yml")
        self.assertIn("HANDOVER_STORAGE_PATH", compose)
        self.assertIn("HANDOVER_AUDIT_STORAGE_PATH", compose)
        self.assertIn(":/app/handover", compose)
        self.assertIn(":/app/handover-audit", compose)


if __name__ == "__main__":
    unittest.main()
