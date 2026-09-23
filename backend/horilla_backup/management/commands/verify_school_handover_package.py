from __future__ import annotations

import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from horilla_backup.handover import (
    append_receipt,
    assert_isolated_path,
    load_and_verify_manifest,
    resolve_package,
    safe_extract_archive,
    verify_detached_checksum,
)


class Command(BaseCommand):
    help = "Verify an open-format school handover package and every manifest checksum."

    def add_arguments(self, parser):
        parser.add_argument("package")
        parser.add_argument("--operator", required=True)

    def handle(self, *args, **options):
        operator = str(options["operator"] or "").strip()
        if not operator:
            raise CommandError("--operator is required")
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
            temporary = Path(tempfile.mkdtemp(prefix=".handover-verify-", dir=package.parent))
            try:
                safe_extract_archive(package, temporary)
                manifest = load_and_verify_manifest(temporary)
            finally:
                shutil.rmtree(temporary, ignore_errors=True)
            append_receipt(
                receipt_root,
                {
                    "event": "VERIFIED",
                    "at": datetime.now(timezone.utc).isoformat(),
                    "package_id": manifest.get("package_id"),
                    "package": package.name,
                    "sha256": digest,
                    "operator": operator,
                },
            )
        except Exception as exc:
            raise CommandError(f"School handover verification failed: {exc}") from exc
        self.stdout.write(
            self.style.SUCCESS(
                f"SCHOOL_HANDOVER_VERIFIED package={package} sha256={digest}"
            )
        )
