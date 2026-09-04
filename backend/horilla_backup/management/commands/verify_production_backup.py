import json
import tempfile
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from horilla_backup.production import decrypt_file, resolve_bundle, sha256_file


class Command(BaseCommand):
    help = "Verify checksums and authenticated encryption for a backup bundle."

    def add_arguments(self, parser):
        parser.add_argument("bundle")

    def handle(self, *args, **options):
        try:
            bundle = resolve_bundle(settings.PRODUCTION_BACKUP_ROOT, options["bundle"])
            manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
            if manifest.get("format") != "renshi-production-backup-v1":
                raise ValueError("unsupported backup manifest format")
            with tempfile.TemporaryDirectory(dir=bundle) as temporary:
                for name, metadata in manifest["artifacts"].items():
                    artifact = bundle / name
                    if sha256_file(artifact) != metadata["sha256"]:
                        raise ValueError(f"checksum mismatch for {name}")
                    decrypt_file(
                        artifact,
                        Path(temporary) / name.removesuffix(".enc"),
                        settings.PRODUCTION_BACKUP_ENCRYPTION_KEY,
                    )
        except Exception as exc:
            raise CommandError(f"Backup verification failed: {exc}") from exc
        self.stdout.write(self.style.SUCCESS(f"PRODUCTION_BACKUP_VERIFIED bundle={bundle}"))
