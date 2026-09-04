import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from horilla_backup.mysqldump import resolve_mysql_client
from horilla_backup.production import decrypt_file, resolve_bundle, sha256_file


class Command(BaseCommand):
    help = "Restore a verified bundle into a separate target database and optional empty media directory."

    def add_arguments(self, parser):
        parser.add_argument("bundle")
        parser.add_argument("--target-database", required=True)
        parser.add_argument("--confirm-target", required=True)
        parser.add_argument("--media-target")

    def handle(self, *args, **options):
        target = str(options["target_database"]).strip()
        if options["confirm_target"] != target:
            raise CommandError("--confirm-target must exactly match --target-database")
        if not re.fullmatch(r"[A-Za-z0-9_]{1,64}", target):
            raise CommandError(
                "--target-database must contain only letters, digits and underscores"
            )
        source_name = str(settings.DATABASES["default"]["NAME"])
        if target == source_name:
            raise CommandError("Refusing to restore over the live configured database")
        password = os.environ.get("RESTORE_DATABASE_PASSWORD", "")
        user = os.environ.get("RESTORE_DATABASE_USER", "")
        if not user or not password:
            raise CommandError("RESTORE_DATABASE_USER and RESTORE_DATABASE_PASSWORD are required")

        try:
            media_target = self._validate_media_target(options.get("media_target"))
            client = resolve_mysql_client()
            host = os.environ.get("RESTORE_DATABASE_HOST", "db")
            port = os.environ.get("RESTORE_DATABASE_PORT", "3306")
            environment = os.environ.copy()
            environment["MYSQL_PWD"] = password
            self._require_empty_database(
                client=client,
                target=target,
                host=host,
                port=port,
                user=user,
                environment=environment,
            )
            bundle = resolve_bundle(settings.PRODUCTION_BACKUP_ROOT, options["bundle"])
            manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
            if manifest.get("format") != "renshi-production-backup-v1":
                raise ValueError("unsupported backup manifest format")
            database_artifact = self._verified_artifact(bundle, manifest, "database.sql.enc")
            media_artifact = self._verified_artifact(bundle, manifest, "media.tar.gz.enc")
            with tempfile.TemporaryDirectory(dir=bundle) as temporary:
                sql = decrypt_file(
                    database_artifact,
                    Path(temporary) / "database.sql",
                    settings.PRODUCTION_BACKUP_ENCRYPTION_KEY,
                )
                prepared_media = None
                media_staging_root = None
                if media_target is not None:
                    media_archive = decrypt_file(
                        media_artifact,
                        Path(temporary) / "media.tar.gz",
                        settings.PRODUCTION_BACKUP_ENCRYPTION_KEY,
                    )
                    media_target.parent.mkdir(parents=True, exist_ok=True)
                    media_staging_root = Path(
                        tempfile.mkdtemp(
                            prefix=f".{media_target.name}.restore-",
                            dir=media_target.parent,
                        )
                    )
                    prepared_media = media_staging_root / "media"
                    prepared_media.mkdir()
                    try:
                        with tarfile.open(media_archive, "r:gz") as archive:
                            archive.extractall(prepared_media, filter="data")
                    except Exception:
                        shutil.rmtree(media_staging_root, ignore_errors=True)
                        raise

                command = [
                    client,
                    "--host", host,
                    "--port", port,
                    "--user", user,
                    "--binary-mode",
                    f"--database={target}",
                ]
                try:
                    with sql.open("rb") as source:
                        subprocess.run(command, stdin=source, env=environment, check=True)
                    if prepared_media is not None:
                        if media_target.exists():
                            media_target.rmdir()
                        os.replace(prepared_media, media_target)
                finally:
                    if media_staging_root is not None:
                        shutil.rmtree(media_staging_root, ignore_errors=True)
        except Exception as exc:
            raise CommandError(f"Production restore failed: {exc}") from exc
        self.stdout.write(self.style.SUCCESS(f"PRODUCTION_RESTORE_OK target={target}"))

    @staticmethod
    def _validate_media_target(value):
        if not value:
            return None
        target = Path(value).resolve()
        if target.exists() and (not target.is_dir() or any(target.iterdir())):
            raise ValueError("media target must be absent or an empty directory")
        return target

    @staticmethod
    def _require_empty_database(*, client, target, host, port, user, environment):
        command = [
            client,
            "--host", host,
            "--port", port,
            "--user", user,
            f"--database={target}",
            "--batch",
            "--skip-column-names",
            "--execute",
            (
                "SELECT COUNT(*) FROM information_schema.tables "
                "WHERE table_schema = DATABASE()"
            ),
        ]
        result = subprocess.run(
            command,
            check=True,
            text=True,
            capture_output=True,
            env=environment,
        )
        try:
            table_count = int(result.stdout.strip())
        except (TypeError, ValueError) as exc:
            raise ValueError("target database preflight returned an invalid table count") from exc
        if table_count:
            raise ValueError(
                f"target database must be empty; found {table_count} existing tables"
            )

    @staticmethod
    def _verified_artifact(bundle, manifest, name):
        artifact = bundle / name
        metadata = manifest["artifacts"][name]
        if sha256_file(artifact) != metadata["sha256"]:
            raise ValueError(f"checksum mismatch for {name}")
        return artifact
