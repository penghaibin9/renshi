import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from cryptography.exceptions import InvalidTag
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings

from horilla_backup.production import (
    ProductionBackupError,
    decrypt_file,
    encrypt_file,
    resolve_bundle,
    sha256_file,
)
from horilla_backup.mysqldump import rewrite_generated_column_inserts
from horilla_backup.management.commands.restore_production_backup import (
    Command as RestoreCommand,
)
from horilla_backup.scheduler import _ensure_legacy_gdrive_allowed


class ProductionBackupPrimitiveTests(SimpleTestCase):
    secret = "correct-horse-battery-staple-for-backups"

    def test_encrypted_round_trip_and_checksum(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source.bin"
            encrypted = root / "backup.enc"
            restored = root / "restored.bin"
            source.write_bytes((b"renshi-production-backup\0" * 4096) + b"end")
            encrypt_file(source, encrypted, self.secret)
            self.assertNotIn(source.read_bytes()[:32], encrypted.read_bytes())
            self.assertEqual(len(sha256_file(encrypted)), 64)
            decrypt_file(encrypted, restored, self.secret)
            self.assertEqual(restored.read_bytes(), source.read_bytes())

    def test_wrong_key_fails_authenticated_decryption(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source"
            source.write_bytes(b"private personnel backup")
            encrypted = encrypt_file(source, root / "backup.enc", self.secret)
            with self.assertRaises(InvalidTag):
                decrypt_file(encrypted, root / "restored", "different-secret-key-of-sufficient-length")
            self.assertFalse((root / "restored").exists())

    def test_short_key_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source"
            source.write_bytes(b"data")
            with self.assertRaises(ProductionBackupError):
                encrypt_file(source, root / "backup.enc", "short")

    def test_bundle_resolution_cannot_escape_root(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "valid").mkdir()
            self.assertEqual(resolve_bundle(root, "valid"), (root / "valid").resolve())
            with self.assertRaises(ProductionBackupError):
                resolve_bundle(root, "../outside")

    def test_generated_columns_are_rewritten_to_default(self):
        with tempfile.TemporaryDirectory() as folder:
            dump = Path(folder) / "database.sql"
            dump.write_text(
                "INSERT INTO `application` (`id`, `payload`, `active_guard`) "
                "VALUES ('1','comma, quote\\' and slash\\\\',1);\n"
                "INSERT INTO `other` (`id`) VALUES (2);\n",
                encoding="utf-8",
            )
            replacements = rewrite_generated_column_inserts(
                dump, {"application": {"active_guard"}}
            )
            content = dump.read_text(encoding="utf-8")
            self.assertEqual(replacements, 1)
            self.assertIn("'comma, quote\\' and slash\\\\',DEFAULT", content)
            self.assertIn("INSERT INTO `other`", content)

    @override_settings(IS_PRODUCTION=True)
    def test_legacy_plaintext_gdrive_scheduler_is_blocked_in_production(self):
        with self.assertRaisesMessage(RuntimeError, "disabled in production"):
            _ensure_legacy_gdrive_allowed()
        urls_source = (Path(__file__).resolve().parent / "urls.py").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            'urlpatterns = [] if getattr(settings, "IS_PRODUCTION", False)',
            urls_source,
        )


class ProductionRestorePreflightTests(SimpleTestCase):
    def test_restore_target_name_is_restricted_before_external_commands(self):
        command = RestoreCommand()
        with self.assertRaisesMessage(CommandError, "letters, digits and underscores"):
            command.handle(
                bundle="valid",
                target_database="restore-db;DROP",
                confirm_target="restore-db;DROP",
                media_target=None,
            )

    @patch("horilla_backup.management.commands.restore_production_backup.subprocess.run")
    def test_empty_database_preflight_uses_selected_database(self, run):
        run.return_value = MagicMock(stdout="0\n")
        RestoreCommand._require_empty_database(
            client="mysql",
            target="renshi_restore_drill",
            host="db",
            port="3306",
            user="restore_user",
            environment={"MYSQL_PWD": "not-in-argv"},
        )
        invoked = run.call_args.args[0]
        self.assertIn("--database=renshi_restore_drill", invoked)
        self.assertNotIn("not-in-argv", invoked)
        self.assertIn("DATABASE()", invoked[-1])

    @patch("horilla_backup.management.commands.restore_production_backup.subprocess.run")
    def test_nonempty_database_is_rejected_before_import(self, run):
        run.return_value = MagicMock(stdout="7\n")
        with self.assertRaisesMessage(ValueError, "found 7 existing tables"):
            RestoreCommand._require_empty_database(
                client="mysql",
                target="renshi_restore_drill",
                host="db",
                port="3306",
                user="restore_user",
                environment={"MYSQL_PWD": "secret"},
            )

    def test_media_target_must_be_empty_before_database_restore(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "media"
            target.mkdir()
            (target / "existing.txt").write_text("do not overwrite", encoding="utf-8")
            with self.assertRaisesMessage(ValueError, "absent or an empty directory"):
                RestoreCommand._validate_media_target(target)
