from __future__ import annotations

import json
import os
import shutil
import tarfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from horilla_backup.mysqldump import dump_mysql_db
from horilla_backup.production import encrypt_file, sha256_file


class Command(BaseCommand):
    help = "Create an encrypted MySQL + media backup bundle with checksums."

    def handle(self, *args, **options):
        if connection.vendor != "mysql":
            raise CommandError("Production backup requires MySQL")
        root = Path(settings.PRODUCTION_BACKUP_ROOT).resolve()
        root.mkdir(parents=True, exist_ok=True)
        secret = settings.PRODUCTION_BACKUP_ENCRYPTION_KEY
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        bundle_name = f"{stamp}-{uuid.uuid4().hex[:8]}"
        staging = root / f".staging-{bundle_name}"
        final = root / bundle_name
        staging.mkdir(mode=0o700)
        database_plain = staging / "database.sql"
        media_plain = staging / "media.tar.gz"
        try:
            database = settings.DATABASES["default"]
            dump_mysql_db(
                db_name=database["NAME"],
                username=database["USER"],
                output_file=database_plain,
                password=database.get("PASSWORD"),
                host=database.get("HOST") or "localhost",
                port=database.get("PORT") or 3306,
            )
            database_encrypted = encrypt_file(
                database_plain, staging / "database.sql.enc", secret
            )
            database_plain.unlink(missing_ok=True)

            with tarfile.open(media_plain, "w:gz") as archive:
                media_root = Path(settings.MEDIA_ROOT)
                if media_root.exists():
                    archive.add(media_root, arcname=".", filter=self._safe_tar_member)
            media_encrypted = encrypt_file(
                media_plain, staging / "media.tar.gz.enc", secret
            )
            media_plain.unlink(missing_ok=True)

            manifest = {
                "format": "renshi-production-backup-v1",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "database_vendor": connection.vendor,
                "database_name": str(database["NAME"]),
                "artifacts": {
                    database_encrypted.name: self._artifact(database_encrypted),
                    media_encrypted.name: self._artifact(media_encrypted),
                },
            }
            manifest_path = staging / "manifest.json"
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            os.chmod(manifest_path, 0o600)
            os.replace(staging, final)
            self._prune(root, keep=settings.PRODUCTION_BACKUP_RETENTION_COUNT)
        except Exception as exc:
            database_plain.unlink(missing_ok=True)
            media_plain.unlink(missing_ok=True)
            shutil.rmtree(staging, ignore_errors=True)
            raise CommandError(f"Production backup failed: {exc}") from exc

        self.stdout.write(self.style.SUCCESS(f"PRODUCTION_BACKUP_OK bundle={final}"))

    @staticmethod
    def _safe_tar_member(info):
        return info if info.isfile() or info.isdir() else None

    @staticmethod
    def _artifact(path):
        return {"bytes": path.stat().st_size, "sha256": sha256_file(path)}

    @staticmethod
    def _prune(root: Path, keep: int):
        keep = max(int(keep), 2)
        bundles = sorted(
            (
                child
                for child in root.iterdir()
                if child.is_dir()
                and not child.is_symlink()
                and (child / "manifest.json").is_file()
            ),
            key=lambda item: item.name,
            reverse=True,
        )
        for obsolete in bundles[keep:]:
            if obsolete.resolve().parent == root:
                shutil.rmtree(obsolete)
