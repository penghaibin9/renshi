import tempfile
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from horilla_backup.production import decrypt_file, resolve_bundle, verified_bundle_manifest
from horilla_backup.handover import inspect_archive


class Command(BaseCommand):
    help = "Verify checksums and authenticated encryption for a backup bundle."

    def add_arguments(self, parser):
        parser.add_argument("bundle")

    def handle(self, *args, **options):
        try:
            bundle = resolve_bundle(settings.PRODUCTION_BACKUP_ROOT, options["bundle"])
            manifest = verified_bundle_manifest(bundle)
            with tempfile.TemporaryDirectory(dir=bundle) as temporary:
                for name, metadata in manifest["artifacts"].items():
                    artifact = bundle / name
                    decrypted = decrypt_file(
                        artifact,
                        Path(temporary) / name.removesuffix(".enc"),
                        settings.PRODUCTION_BACKUP_ENCRYPTION_KEY,
                    )
                    if name == "media.tar.gz.enc":
                        inspect_archive(decrypted)
        except Exception as exc:
            raise CommandError(f"Backup verification failed: {exc}") from exc
        self.stdout.write(self.style.SUCCESS(f"PRODUCTION_BACKUP_VERIFIED bundle={bundle}"))
