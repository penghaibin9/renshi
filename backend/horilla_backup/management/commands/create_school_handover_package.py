from __future__ import annotations

import json
import os
import shutil
import tarfile
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.urls import get_resolver

from horilla_backup.handover import (
    HANDOVER_CONFIRMATION,
    HANDOVER_FORMAT,
    append_receipt,
    artifact_metadata,
    assert_isolated_path,
    sha256_file,
    write_api_route_inventory,
    write_configuration_catalog,
    write_interface_mapping_catalog,
    write_migration_state,
    write_runtime_configuration,
    write_schema_dictionary,
    write_secret_handover_requirements,
    write_dump_row_counts,
)
from horilla_backup.mysqldump import dump_mysql_db


class Command(BaseCommand):
    help = (
        "Create a procurement-grade open-format school handover package. "
        "This is not the encrypted disaster-recovery backup command."
    )

    def add_arguments(self, parser):
        parser.add_argument("--recipient", required=True)
        parser.add_argument("--purpose", required=True)
        parser.add_argument("--operator", required=True)
        parser.add_argument("--confirm-sensitive-export", required=True)

    def handle(self, *args, **options):
        if connection.vendor != "mysql":
            raise CommandError("School handover export requires MySQL")
        if options["confirm_sensitive_export"] != HANDOVER_CONFIRMATION:
            raise CommandError(
                "Sensitive HR export was not confirmed. Pass the exact documented confirmation token."
            )
        recipient = self._required_text(options["recipient"], "recipient")
        purpose = self._required_text(options["purpose"], "purpose")
        operator = self._required_text(options["operator"], "operator")

        root = Path(settings.SCHOOL_HANDOVER_ROOT).resolve()
        receipt_root = Path(settings.SCHOOL_HANDOVER_RECEIPT_ROOT).resolve()
        self._validate_private_roots(root, receipt_root)
        root.mkdir(parents=True, exist_ok=True)
        os.chmod(root, 0o700)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        package_id = f"{stamp}-{uuid.uuid4().hex[:8]}"
        final_package = root / f"school-handover-{package_id}.tar.gz"
        final_checksum = root / f"school-handover-{package_id}.tar.gz.sha256"

        staging_parent = Path(tempfile.mkdtemp(prefix=".handover-", dir=root))
        staging = staging_parent / "payload"
        staging.mkdir(mode=0o700)
        try:
            database = settings.DATABASES["default"]
            database_path = staging / "database.sql"
            dump_mysql_db(
                db_name=database["NAME"],
                username=database["USER"],
                output_file=database_path,
                password=database.get("PASSWORD"),
                host=database.get("HOST") or "localhost",
                port=database.get("PORT") or 3306,
            )
            os.chmod(database_path, 0o600)

            media_path = staging / "media.tar.gz"
            self._archive_media(Path(settings.MEDIA_ROOT), media_path)

            schema_stats = write_schema_dictionary(
                connection,
                staging / "schema_dictionary.csv",
                staging / "schema_dictionary.json",
            )
            row_count_stats = write_dump_row_counts(
                database_path,
                staging / "table_row_counts.csv",
                staging / "table_row_counts.json",
            )
            migration_stats = write_migration_state(
                connection, staging / "migration_state.json"
            )
            route_stats = write_api_route_inventory(
                get_resolver(), staging / "api_route_inventory.csv"
            )
            configuration_stats = write_configuration_catalog(
                connection,
                staging / "configuration_catalog.csv",
                staging / "configuration_catalog.json",
            )
            mapping_stats = write_interface_mapping_catalog(
                connection, staging / "interface_mapping_catalog.json"
            )
            write_runtime_configuration(
                settings, connection, staging / "runtime_configuration.json"
            )
            secret_requirements = write_secret_handover_requirements(
                settings, staging / "secret_handover_requirements.json"
            )
            copied_docs = self._copy_portability_docs(staging / "delivery_docs")
            (staging / "README-HANDOVER.txt").write_text(
                self._readme(recipient=recipient, purpose=purpose), encoding="utf-8"
            )

            artifacts = {}
            for path in sorted(staging.rglob("*")):
                if path.is_file() and path.name != "manifest.json":
                    relative = path.relative_to(staging).as_posix()
                    artifacts[relative] = artifact_metadata(path)

            manifest = {
                "format": HANDOVER_FORMAT,
                "package_id": package_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "recipient": recipient,
                "purpose": purpose,
                "operator": operator,
                "database_vendor": connection.vendor,
                "database_name": str(database["NAME"]),
                "open_format_contract": {
                    "database": "plain MySQL logical SQL dump",
                    "media": "POSIX-compatible tar.gz",
                    "data_dictionary": ["UTF-8 CSV", "JSON"],
                    "metadata": "JSON/CSV/plain text",
                    "proprietary_encryption_required_to_restore": False,
                    "transport_security": (
                        "Package contains sensitive HR data. Transfer encryption must use a "
                        "school-controlled standard mechanism/key outside this package."
                    ),
                },
                "secret_handover": {
                    "values_in_package": False,
                    "field_encryption_key_ids": [
                        item for item in secret_requirements["requirements"][0]["configured_key_ids"]
                    ],
                    "separate_school_controlled_channel_required": True,
                },
                "source_delivery": {
                    "included": False,
                    "required_separately": True,
                    "note": (
                        "Deliver the matching signed source release separately when the contract "
                        "requires source delivery; secrets and runtime credentials are never embedded."
                    ),
                },
                "stats": {
                    **schema_stats,
                    **row_count_stats,
                    **migration_stats,
                    **route_stats,
                    **configuration_stats,
                    **mapping_stats,
                    "delivery_doc_count": copied_docs,
                },
                "artifacts": artifacts,
            }
            manifest_path = staging / "manifest.json"
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            os.chmod(manifest_path, 0o600)

            self._create_package(staging, final_package)
            checksum = sha256_file(final_package)
            final_checksum.write_text(
                f"{checksum}  {final_package.name}\n", encoding="utf-8"
            )
            os.chmod(final_checksum, 0o600)
            append_receipt(
                receipt_root,
                {
                    "event": "CREATED",
                    "at": datetime.now(timezone.utc).isoformat(),
                    "package_id": package_id,
                    "package": final_package.name,
                    "sha256": checksum,
                    "recipient": recipient,
                    "purpose": purpose,
                    "operator": operator,
                },
            )
        except Exception as exc:
            final_package.unlink(missing_ok=True)
            final_checksum.unlink(missing_ok=True)
            raise CommandError(f"School handover export failed: {exc}") from exc
        finally:
            shutil.rmtree(staging_parent, ignore_errors=True)

        self.stdout.write(
            self.style.SUCCESS(
                f"SCHOOL_HANDOVER_OK package={final_package} sha256={checksum}"
            )
        )

    @staticmethod
    def _validate_private_roots(root: Path, receipt_root: Path):
        forbidden = [
            Path(settings.MEDIA_ROOT),
            Path(settings.STATIC_ROOT),
            Path(settings.REPO_ROOT) / "frontend",
        ]
        assert_isolated_path(root, forbidden, label="SCHOOL_HANDOVER_ROOT")
        assert_isolated_path(
            receipt_root, forbidden, label="SCHOOL_HANDOVER_RECEIPT_ROOT"
        )
        if (
            root == receipt_root
            or root in receipt_root.parents
            or receipt_root in root.parents
        ):
            raise CommandError(
                "SCHOOL_HANDOVER_ROOT and SCHOOL_HANDOVER_RECEIPT_ROOT must be separate paths"
            )

    @staticmethod
    def _required_text(value, label):
        text = str(value or "").strip()
        if not text or len(text) > 500:
            raise CommandError(f"--{label} must contain 1 to 500 characters")
        return text

    @staticmethod
    def _archive_media(media_root: Path, destination: Path):
        with tarfile.open(destination, "w:gz") as archive:
            if media_root.exists():
                for path in sorted(media_root.rglob("*")):
                    if path.is_symlink():
                        continue
                    relative = path.relative_to(media_root).as_posix()
                    archive.add(path, arcname=relative, recursive=False)
        os.chmod(destination, 0o600)

    @staticmethod
    def _create_package(staging: Path, destination: Path):
        temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
        try:
            with tarfile.open(temporary, "w:gz") as archive:
                for path in sorted(staging.rglob("*")):
                    if path.is_file():
                        archive.add(path, arcname=path.relative_to(staging).as_posix())
            os.chmod(temporary, 0o600)
            os.replace(temporary, destination)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise

    @staticmethod
    def _copy_portability_docs(destination: Path) -> int:
        destination.mkdir(parents=True, exist_ok=True)
        repo_root = Path(settings.REPO_ROOT)
        candidates = [
            (repo_root / ".env.dist", "environment-template.env"),
            (repo_root / "docker-compose.yml", "docker-compose.yml"),
            (repo_root / "docker-compose.prod.yml", "docker-compose.prod.yml"),
            (repo_root / "deploy/docker/README.md", "docker-deployment.md"),
            (repo_root / "docs/PRODUCTION_RUNBOOK.md", "production-runbook.md"),
            (repo_root / "docs/qa/SCHOOL_HANDOVER_ACCEPTANCE_CHECKLIST.md", "school-handover-acceptance-checklist.md"),
            (repo_root / "docs/TargetDatabaseCompatibilityMatrix.md", "database-compatibility.md"),
            (repo_root / "docs/TenantIdentityPermissionMatrix.md", "tenant-permission-matrix.md"),
            (repo_root / "docs/GlobalAuthorityOwnershipMatrix.md", "authority-ownership-matrix.md"),
            (repo_root / "docs/CrossDomainProviderEventMatrix.md", "provider-event-matrix.md"),
            (repo_root / "docs/GlobalReconciliationMatrix.md", "reconciliation-matrix.md"),
        ]
        copied = 0
        for source, name in candidates:
            if source.is_file():
                shutil.copy2(source, destination / name)
                copied += 1
        return copied

    @staticmethod
    def _readme(*, recipient: str, purpose: str) -> str:
        return f"""跃科高校人事系统学校移交包\n\n接收方：{recipient}\n用途：{purpose}\n\n本包用于学校数据与运行资料移交，不替代日常加密灾备。\n数据库为标准 MySQL SQL，媒体为标准 tar.gz，字典与清单为 CSV/JSON。\ntable_row_counts.csv/json 记录 database.sql 实际序列化的数据行数，恢复后逐表核对。\n本包必须与同名 .sha256 侧车校验文件一起交付，校验/恢复前会先验证外层包摘要。\n恢复本包不依赖跃科私有解密算法或私有文件格式。\n\n安全要求：\n1. 本包包含敏感人事数据，仅允许授权人员处理。\n2. 传输/存储时应使用由学校控制的标准加密机制和密钥。\n3. runtime_configuration.json 不包含密码、SECRET_KEY、Redis 密码、字段加密密钥、备份密钥或第三方 token。\n4. secret_handover_requirements.json 只列密钥类别/Key ID，不含密钥值；解密既有敏感字段所需密钥必须通过学校控制的独立安全通道交接。\n5. 源代码按合同要求使用与本包版本匹配的签字源码发布包单独交付。\n6. 恢复前先执行 verify_school_handover_package，再恢复到名称不同的空数据库。\n"""
