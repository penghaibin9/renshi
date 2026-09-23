from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from horilla_backup.handover import (
    HANDOVER_RESTORE_CONFIRMATION,
    append_receipt,
    assert_isolated_path,
    load_and_verify_manifest,
    resolve_package,
    safe_extract_archive,
    restore_media_target_for_settings,
    verify_detached_checksum,
)
from horilla_backup.mysqldump import resolve_mysql_client


class Command(BaseCommand):
    help = "Restore a verified school handover package to a separate empty MySQL database."

    def add_arguments(self, parser):
        parser.add_argument("package")
        parser.add_argument("--target-database", required=True)
        parser.add_argument("--confirm-target", required=True)
        parser.add_argument("--media-target")
        parser.add_argument("--operator", required=True)
        parser.add_argument("--confirm-restore-policy", required=True)

    def handle(self, *args, **options):
        target = str(options["target_database"] or "").strip()
        operator = str(options["operator"] or "").strip()
        if not operator:
            raise CommandError("--operator is required")
        if options["confirm_target"] != target:
            raise CommandError("--confirm-target must exactly match --target-database")
        if options["confirm_restore_policy"] != HANDOVER_RESTORE_CONFIRMATION:
            raise CommandError("The empty-database restore policy was not explicitly confirmed")
        if not re.fullmatch(r"[A-Za-z0-9_]{1,64}", target):
            raise CommandError(
                "--target-database must contain only letters, digits and underscores"
            )
        source_database = str(settings.DATABASES["default"]["NAME"])
        if target.casefold() == source_database.casefold():
            raise CommandError("Refusing to restore over the live configured database")
        try:
            media_target = self._validate_media_target(options.get("media_target"))
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        except RuntimeError as exc:
            raise CommandError(str(exc)) from exc

        user = os.environ.get("RESTORE_DATABASE_USER", "")
        password = os.environ.get("RESTORE_DATABASE_PASSWORD", "")
        if not user or not password:
            raise CommandError("RESTORE_DATABASE_USER and RESTORE_DATABASE_PASSWORD are required")
        host = os.environ.get("RESTORE_DATABASE_HOST", "db")
        port = os.environ.get("RESTORE_DATABASE_PORT", "3306")
        environment = os.environ.copy()
        environment["MYSQL_PWD"] = password
        client = resolve_mysql_client()

        package = None
        temporary = None
        media_staging_root = None
        prepared_media = None
        try:
            root = assert_isolated_path(
                settings.SCHOOL_HANDOVER_ROOT,
                [settings.MEDIA_ROOT, settings.STATIC_ROOT, Path(settings.REPO_ROOT) / "frontend"],
                label="SCHOOL_HANDOVER_ROOT",
            )
            receipt_root = assert_isolated_path(
                settings.SCHOOL_HANDOVER_RECEIPT_ROOT,
                [settings.MEDIA_ROOT, settings.STATIC_ROOT, Path(settings.REPO_ROOT) / "frontend"],
                label="SCHOOL_HANDOVER_RECEIPT_ROOT",
            )
            package = resolve_package(root, options["package"])
            digest = verify_detached_checksum(package)
            temporary = Path(tempfile.mkdtemp(prefix=".handover-restore-", dir=package.parent))
            safe_extract_archive(package, temporary)
            manifest = load_and_verify_manifest(temporary)
            manifest["_extracted_root"] = str(temporary)
            if media_target is not None:
                media_staging_root, prepared_media = self._prepare_media_archive(
                    temporary / "media.tar.gz", media_target
                )
            self._require_empty_database(
                client=client,
                target=target,
                host=host,
                port=port,
                user=user,
                environment=environment,
            )
            if media_target is not None:
                self._validate_media_target(media_target)
            self._restore_database(
                client=client,
                sql_path=temporary / "database.sql",
                target=target,
                host=host,
                port=port,
                user=user,
                environment=environment,
            )
            postcheck = self._post_restore_check(
                client=client,
                target=target,
                host=host,
                port=port,
                user=user,
                environment=environment,
                manifest=manifest,
            )
            if prepared_media is not None:
                self._validate_media_target(media_target)
                if media_target.exists():
                    media_target.rmdir()
                os.replace(prepared_media, media_target)
            append_receipt(
                receipt_root,
                {
                    "event": "RESTORED",
                    "at": datetime.now(timezone.utc).isoformat(),
                    "package_id": manifest.get("package_id"),
                    "package": package.name,
                    "sha256": digest,
                    "target_database": target,
                    "operator": operator,
                    "postcheck": postcheck,
                },
            )
        except Exception as exc:
            raise CommandError(f"School handover restore failed: {exc}") from exc
        finally:
            if media_staging_root is not None:
                shutil.rmtree(media_staging_root, ignore_errors=True)
            if temporary is not None:
                shutil.rmtree(temporary, ignore_errors=True)

        self.stdout.write(
            self.style.SUCCESS(
                f"SCHOOL_HANDOVER_RESTORE_OK target={target} tables={postcheck['table_count']} "
                f"migrations={postcheck['migration_count']} rows={postcheck['total_rows']}"
            )
        )

    @staticmethod
    def _validate_media_target(value):
        return restore_media_target_for_settings(value, settings)

    @staticmethod
    def _mysql_base(client, target, host, port, user):
        return [
            client,
            "--host", str(host),
            "--port", str(port),
            "--user", str(user),
            f"--database={target}",
        ]

    @classmethod
    def _query_scalar(cls, *, client, target, host, port, user, environment, sql):
        command = cls._mysql_base(client, target, host, port, user) + [
            "--batch", "--skip-column-names", "--execute", sql
        ]
        result = subprocess.run(
            command, check=True, text=True, capture_output=True, env=environment
        )
        return result.stdout.strip()

    @classmethod
    def _require_empty_database(cls, *, client, target, host, port, user, environment):
        raw = cls._query_scalar(
            client=client,
            target=target,
            host=host,
            port=port,
            user=user,
            environment=environment,
            sql=(
                "SELECT COUNT(*) FROM information_schema.tables "
                "WHERE table_schema = DATABASE()"
            ),
        )
        try:
            count = int(raw)
        except ValueError as exc:
            raise ValueError("target database preflight returned an invalid table count") from exc
        if count:
            raise ValueError(f"target database must be empty; found {count} existing tables")

    @classmethod
    def _restore_database(cls, *, client, sql_path, target, host, port, user, environment):
        if not sql_path.is_file() or sql_path.stat().st_size == 0:
            raise ValueError("handover database.sql is missing or empty")
        command = cls._mysql_base(client, target, host, port, user) + ["--binary-mode"]
        with sql_path.open("rb") as source:
            subprocess.run(command, stdin=source, check=True, env=environment)

    @staticmethod
    def _prepare_media_archive(archive_path: Path, media_target: Path):
        """Fully validate/extract media before mutating the target database."""
        if not archive_path.is_file():
            raise ValueError("handover media.tar.gz is missing")
        media_target.parent.mkdir(parents=True, exist_ok=True)
        staging_root = Path(
            tempfile.mkdtemp(prefix=f".{media_target.name}.handover-", dir=media_target.parent)
        )
        prepared = staging_root / "media"
        prepared.mkdir()
        try:
            safe_extract_archive(archive_path, prepared)
            return staging_root, prepared
        except Exception:
            shutil.rmtree(staging_root, ignore_errors=True)
            raise

    @classmethod
    def _post_restore_check(
        cls, *, client, target, host, port, user, environment, manifest
    ):
        table_count = int(
            cls._query_scalar(
                client=client,
                target=target,
                host=host,
                port=port,
                user=user,
                environment=environment,
                sql=(
                    "SELECT COUNT(*) FROM information_schema.tables "
                    "WHERE table_schema = DATABASE()"
                ),
            )
        )
        migration_count = int(
            cls._query_scalar(
                client=client,
                target=target,
                host=host,
                port=port,
                user=user,
                environment=environment,
                sql="SELECT COUNT(*) FROM django_migrations",
            )
        )
        expected_tables = int(manifest.get("stats", {}).get("table_count", -1))
        expected_migrations = int(manifest.get("stats", {}).get("migration_count", -1))
        if expected_tables >= 0 and table_count != expected_tables:
            raise ValueError(
                f"post-restore table count mismatch: expected {expected_tables}, got {table_count}"
            )
        if expected_migrations >= 0 and migration_count != expected_migrations:
            raise ValueError(
                "post-restore migration count mismatch: "
                f"expected {expected_migrations}, got {migration_count}"
            )
        row_count_path = Path(manifest.get("_extracted_root", "")) / "table_row_counts.json"
        # The caller annotates the verified manifest with its extraction root so
        # exact source row-count evidence can be checked after import.
        if not row_count_path.is_file():
            raise ValueError("handover table_row_counts.json is missing after verification")
        try:
            expected_rows = json.loads(row_count_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid table_row_counts.json: {exc}") from exc
        if not isinstance(expected_rows, list):
            raise ValueError("table_row_counts.json must contain a list")
        mismatches = []
        restored_total_rows = 0
        seen_tables = set()
        for item in expected_rows:
            if not isinstance(item, dict):
                raise ValueError("table_row_counts.json contains an invalid row")
            table_name = str(item.get("table_name", ""))
            if (not table_name or len(table_name) > 64 or any(ord(ch) < 32 for ch in table_name)
                    or table_name.casefold() in seen_tables):
                raise ValueError("table_row_counts.json contains an empty, invalid or duplicate table name")
            seen_tables.add(table_name.casefold())
            expected_count = item.get("row_count")
            if type(expected_count) is not int or expected_count < 0:
                raise ValueError(f"table_row_counts.json has an invalid count for {table_name}")
            quoted = "`" + table_name.replace("`", "``") + "`"
            actual_count = int(
                cls._query_scalar(
                    client=client,
                    target=target,
                    host=host,
                    port=port,
                    user=user,
                    environment=environment,
                    sql=f"SELECT COUNT(*) FROM {quoted}",
                )
            )
            restored_total_rows += actual_count
            if actual_count != expected_count:
                mismatches.append(
                    {
                        "table": table_name,
                        "expected": expected_count,
                        "actual": actual_count,
                    }
                )
        if mismatches:
            preview = ", ".join(
                f"{row['table']}:{row['expected']}->{row['actual']}"
                for row in mismatches[:10]
            )
            raise ValueError(
                f"post-restore exact row-count mismatch in {len(mismatches)} tables: {preview}"
            )
        expected_row_tables = int(
            manifest.get("stats", {}).get("row_count_table_count", -1)
        )
        if expected_row_tables >= 0 and len(expected_rows) != expected_row_tables:
            raise ValueError(
                "row-count evidence table total mismatch: "
                f"expected {expected_row_tables}, got {len(expected_rows)}"
            )
        expected_total_rows = int(
            manifest.get("stats", {}).get("row_count_total_rows", -1)
        )
        if expected_total_rows >= 0 and restored_total_rows != expected_total_rows:
            raise ValueError(
                "post-restore total row count mismatch: "
                f"expected {expected_total_rows}, got {restored_total_rows}"
            )
        return {
            "table_count": table_count,
            "migration_count": migration_count,
            "row_count_table_count": len(expected_rows),
            "total_rows": restored_total_rows,
        }
