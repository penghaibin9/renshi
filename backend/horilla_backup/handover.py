"""Open-format school handover package primitives.

This module is deliberately separate from encrypted production backups.
Production backup optimizes for disaster recovery and confidentiality; a school
handover package optimizes for procurement-grade portability and must remain
readable with standard MySQL/tar/CSV/JSON tooling.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path


HANDOVER_FORMAT = "renshi-school-handover-v1"
HANDOVER_CONFIRMATION = "I_UNDERSTAND_THIS_EXPORT_CONTAINS_SENSITIVE_HR_DATA"
HANDOVER_RESTORE_CONFIRMATION = "RESTORE_TO_EMPTY_DATABASE_ONLY"
CHUNK_BYTES = 1024 * 1024
# Resource ceilings for offline handover verification, not business data limits.
MAX_ARCHIVE_MEMBERS = 200_000
MAX_EXPANDED_BYTES = 100 * 1024 ** 3
MAX_MEMBER_BYTES = 64 * 1024 ** 3


class SchoolHandoverError(RuntimeError):
    """Raised when a school handover package is unsafe or invalid."""


def sha256_file(path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        while chunk := source.read(CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def artifact_metadata(path: Path) -> dict:
    path = Path(path)
    return {"bytes": path.stat().st_size, "sha256": sha256_file(path)}


def verify_detached_checksum(package: Path) -> str:
    """Require and verify the detached SHA-256 created with a handover package."""
    package = Path(package)
    checksum_path = package.with_name(package.name + ".sha256")
    if not checksum_path.is_file():
        raise SchoolHandoverError(
            f"Handover package is missing detached checksum: {checksum_path.name}"
        )
    try:
        line = checksum_path.read_text(encoding="utf-8").strip()
        expected, filename = line.split(None, 1)
        filename = filename.strip()
    except (OSError, ValueError) as exc:
        raise SchoolHandoverError("Invalid detached handover checksum file") from exc
    if len(expected) != 64 or any(ch not in "0123456789abcdefABCDEF" for ch in expected):
        raise SchoolHandoverError("Invalid detached handover SHA-256 value")
    if filename != package.name:
        raise SchoolHandoverError("Detached checksum filename does not match package")
    actual = sha256_file(package)
    if actual.lower() != expected.lower():
        raise SchoolHandoverError(
            f"Detached checksum mismatch: expected {expected.lower()}, got {actual}"
        )
    return actual



def assert_isolated_path(candidate, forbidden_paths, *, label: str) -> Path:
    candidate = Path(candidate).resolve()
    for forbidden in forbidden_paths:
        forbidden = Path(forbidden).resolve()
        if (
            candidate == forbidden
            or forbidden in candidate.parents
            or candidate in forbidden.parents
        ):
            raise SchoolHandoverError(
                f"{label} must be isolated from public/static/media/source web paths"
            )
    return candidate

def validate_restore_media_target(value, *, forbidden_paths=()):
    """Preflight a private restore destination without creating or deleting it.

    Empty production MEDIA_ROOT is still production; emptiness is not consent.
    Reject symbolic ancestors before resolve() can hide their original identity.
    """
    if not value:
        return None
    candidate = Path(value).expanduser().absolute()
    if ".." in candidate.parts or any(path.is_symlink() for path in (candidate, *candidate.parents)):
        raise SchoolHandoverError("Restore media path must not contain links or parent traversal")
    target = assert_isolated_path(candidate, [p for p in forbidden_paths if p], label="Restore media target")
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        raise SchoolHandoverError("media target must be absent or an empty directory")
    return target


def restore_media_target_for_settings(value, settings):
    forbidden = [getattr(settings, name, None) for name in (
        "MEDIA_ROOT", "STATIC_ROOT", "PRODUCTION_BACKUP_ROOT", "SCHOOL_HANDOVER_ROOT",
        "SCHOOL_HANDOVER_RECEIPT_ROOT")]
    repo = getattr(settings, "REPO_ROOT", None)
    if repo:
        forbidden.append(Path(repo))
    return validate_restore_media_target(value, forbidden_paths=forbidden)


def resolve_package(root, package_name: str) -> Path:
    root = Path(root).resolve()
    candidate = (root / str(package_name)).resolve()
    if candidate.parent != root or not candidate.is_file():
        raise SchoolHandoverError(
            "Handover package must be an existing direct child of SCHOOL_HANDOVER_ROOT"
        )
    if not candidate.name.endswith(".tar.gz"):
        raise SchoolHandoverError("Handover package must use the standard .tar.gz format")
    return candidate


def _normalized_member_name(name: str) -> str:
    value = str(name or "").replace("\\", "/")
    if value.startswith("/") or len(value) > 1024 or any(ord(c) < 32 for c in value):
        raise SchoolHandoverError("Handover archive contains an unsafe path")
    parts = [part for part in value.split("/") if part not in {"", "."}]
    if not parts or any(part == ".." or ":" in part or part.endswith((" ", ".")) for part in parts):
        raise SchoolHandoverError("Handover archive contains an unsafe relative path")
    # Artifacts may be handed over to Windows. Reject device/ADS aliases there.
    reserved = {"CON", "PRN", "AUX", "NUL", *{f"COM{i}" for i in range(1,10)}, *{f"LPT{i}" for i in range(1,10)}}
    if any(part.split(".",1)[0].upper() in reserved for part in parts):
        raise SchoolHandoverError("Handover archive contains a reserved path")
    return "/".join(parts)


def _checked_members(archive, *, max_members, max_expanded_bytes, max_member_bytes):
    if min(max_members, max_expanded_bytes, max_member_bytes) <= 0:
        raise SchoolHandoverError("Invalid archive inspection limits")
    items=[]; seen={}; total=0; scanned=0; root_seen=False
    for member in archive:
        scanned += 1
        if scanned > max_members:
            raise SchoolHandoverError("Handover archive exceeds resource limits")
        # Existing encrypted backups include one harmless '.' root directory.
        # It is never materialized or allowed to carry data or links.
        if member.name in {".", "./"}:
            if root_seen or not member.isdir() or member.size != 0:
                raise SchoolHandoverError("Invalid or duplicate archive root directory")
            root_seen = True
            continue
        name=_normalized_member_name(member.name); key=name.casefold()
        if not (member.isfile() or member.isdir()) or member.issparse():
            raise SchoolHandoverError("Handover archive contains forbidden member type")
        if key in seen:
            raise SchoolHandoverError("Handover archive contains duplicate/aliased paths")
        seen[key]=member.isfile()
        total += member.size
        if member.size < 0 or member.size > max_member_bytes or total > max_expanded_bytes or len(items) >= max_members:
            raise SchoolHandoverError("Handover archive exceeds resource limits")
        items.append((member,name))
    for key in seen:
        parts=key.split("/")
        if any(seen.get("/".join(parts[:i])) is True for i in range(1,len(parts))):
            raise SchoolHandoverError("Handover archive contains file/directory collisions")
    return items


def inspect_archive(archive_path: Path, *, max_members=MAX_ARCHIVE_MEMBERS,
        max_expanded_bytes=MAX_EXPANDED_BYTES, max_member_bytes=MAX_MEMBER_BYTES) -> list[str]:
    """Validate types, aliases and bounded resources before extracting anything."""
    with tarfile.open(archive_path,"r:gz") as archive:
        return [name for _,name in _checked_members(archive,max_members=max_members,
            max_expanded_bytes=max_expanded_bytes,max_member_bytes=max_member_bytes)]


def safe_extract_archive(archive_path: Path, destination: Path) -> Path:
    destination=Path(destination)
    if destination.is_symlink():
        raise SchoolHandoverError("Handover destination must not be a symlink")
    destination=destination.resolve()
    destination.mkdir(parents=True,exist_ok=True)
    if any(destination.iterdir()):
        raise SchoolHandoverError("Handover extraction requires an empty private destination")
    os.chmod(destination,0o700)
    # One open archive: validate all members and then read the same file handle.
    with tarfile.open(archive_path,"r:gz") as archive:
        items=_checked_members(archive,max_members=MAX_ARCHIVE_MEMBERS,
            max_expanded_bytes=MAX_EXPANDED_BYTES,max_member_bytes=MAX_MEMBER_BYTES)
        for member,normalized in items:
            target=destination/normalized
            if member.isdir():
                target.mkdir(parents=True,exist_ok=True,mode=0o700);os.chmod(target,0o700);continue
            target.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            source=archive.extractfile(member)
            if source is None: raise SchoolHandoverError("Unable to read handover member")
            fd,name=tempfile.mkstemp(prefix=".handover-",suffix=".tmp",dir=target.parent)
            temporary=Path(name)
            try:
                written=0
                with source,os.fdopen(fd,"wb") as output:
                    while chunk:=source.read(CHUNK_BYTES):
                        written+=len(chunk)
                        if written>member.size: raise SchoolHandoverError("Unexpected member size")
                        output.write(chunk)
                if written!=member.size: raise SchoolHandoverError("Truncated handover member")
                os.chmod(temporary,0o600);os.replace(temporary,target)
            except Exception:
                temporary.unlink(missing_ok=True);raise
    return destination


def load_and_verify_manifest(extracted_root: Path) -> dict:
    manifest_path = Path(extracted_root) / "manifest.json"
    if not manifest_path.is_file():
        raise SchoolHandoverError("Handover package is missing manifest.json")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SchoolHandoverError(f"Invalid handover manifest: {exc}") from exc
    if not isinstance(manifest, dict):
        raise SchoolHandoverError("Handover manifest must be an object")
    if manifest.get("format") != HANDOVER_FORMAT:
        raise SchoolHandoverError("Unsupported handover manifest format")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict) or not artifacts:
        raise SchoolHandoverError("Handover manifest has no artifact inventory")
    required_artifacts = {
        "database.sql",
        "media.tar.gz",
        "schema_dictionary.csv",
        "schema_dictionary.json",
        "table_row_counts.csv",
        "table_row_counts.json",
        "migration_state.json",
        "api_route_inventory.csv",
        "configuration_catalog.csv",
        "configuration_catalog.json",
        "interface_mapping_catalog.json",
        "runtime_configuration.json",
        "secret_handover_requirements.json",
        "README-HANDOVER.txt",
    }
    missing_required = sorted(required_artifacts - set(artifacts))
    if missing_required:
        raise SchoolHandoverError(
            "Handover package is missing required open-format artifacts: "
            + ", ".join(missing_required)
        )
    allowed = {"manifest.json"}
    for relative_name, metadata in artifacts.items():
        normalized = _normalized_member_name(relative_name)
        if normalized != relative_name or normalized in allowed or not isinstance(metadata, dict):
            raise SchoolHandoverError("Non-canonical or duplicate artifact metadata")
        allowed.add(normalized)
        path = Path(extracted_root) / normalized
        if path.is_symlink() or not path.resolve().is_relative_to(Path(extracted_root).resolve()):
            raise SchoolHandoverError("Handover artifact escaped extraction root")
        if not path.is_file():
            raise SchoolHandoverError(f"Handover artifact is missing: {normalized}")
        if type(metadata.get("bytes")) is not int or metadata["bytes"] < 0:
            raise SchoolHandoverError("Invalid artifact byte count")
        if metadata["bytes"] != path.stat().st_size:
            raise SchoolHandoverError(f"Handover artifact size mismatch: {normalized}")
        if str(metadata.get("sha256", "")) != sha256_file(path):
            raise SchoolHandoverError(f"Handover artifact checksum mismatch: {normalized}")
    actual = {
        path.relative_to(extracted_root).as_posix()
        for path in Path(extracted_root).rglob("*")
        if path.is_file()
    }
    unexpected = sorted(actual - allowed)
    if unexpected:
        raise SchoolHandoverError(
            "Handover package contains unmanifested files: " + ", ".join(unexpected[:10])
        )
    database_sql = Path(extracted_root) / "database.sql"
    if database_sql.stat().st_size <= 0:
        raise SchoolHandoverError("Handover database.sql is empty")
    inspect_archive(Path(extracted_root) / "media.tar.gz")
    return manifest


def write_schema_dictionary(connection, csv_path: Path, json_path: Path) -> dict:
    query = """
        SELECT TABLE_NAME, COLUMN_NAME, ORDINAL_POSITION, COLUMN_TYPE,
               IS_NULLABLE, COLUMN_DEFAULT, COLUMN_KEY, EXTRA, COLUMN_COMMENT
          FROM information_schema.COLUMNS
         WHERE TABLE_SCHEMA = DATABASE()
         ORDER BY TABLE_NAME, ORDINAL_POSITION
    """
    columns = [
        "table_name",
        "column_name",
        "ordinal_position",
        "column_type",
        "is_nullable",
        "column_default",
        "column_key",
        "extra",
        "column_comment",
    ]
    with connection.cursor() as cursor:
        cursor.execute(query)
        raw_rows = cursor.fetchall()
    rows = []
    for raw in raw_rows:
        row = {}
        for name, value in zip(columns, raw):
            row[name] = None if value is None else str(value)
        rows.append(row)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    json_path.write_text(
        json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    table_count = len({row["table_name"] for row in rows})
    return {"table_count": table_count, "column_count": len(rows)}


def write_dump_row_counts(dump_path: Path, csv_path: Path, json_path: Path) -> dict:
    """Count the exact rows serialized into database.sql.

    ``dump_mysql_db`` uses ``--skip-extended-insert``, so every dumped data row
    is represented by exactly one INSERT line. Counting the dump itself binds
    restore evidence to the exported snapshot and avoids a race where live DB
    writes after mysqldump would make a separately queried COUNT(*) disagree.
    """
    dump_path = Path(dump_path)
    counts: dict[str, int] = {}
    prefix = "INSERT INTO `"
    with dump_path.open("r", encoding="utf-8", errors="strict", newline="") as source:
        for line in source:
            if not line.startswith(prefix):
                continue
            end = line.find("`", len(prefix))
            if end < 0:
                raise SchoolHandoverError("Malformed INSERT line in database.sql")
            table_name = line[len(prefix):end].replace("``", "`")
            counts[table_name] = counts.get(table_name, 0) + 1

    rows = [
        {"table_name": table_name, "row_count": row_count}
        for table_name, row_count in sorted(counts.items())
    ]
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=["table_name", "row_count"])
        writer.writeheader()
        writer.writerows(rows)
    json_path.write_text(
        json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return {
        "row_count_table_count": len(rows),
        "row_count_total_rows": sum(counts.values()),
        "row_count_source": "database.sql INSERT lines (--skip-extended-insert)",
    }


def write_migration_state(connection, destination: Path) -> dict:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT app, name, applied FROM django_migrations ORDER BY app, name, applied"
        )
        rows = cursor.fetchall()
    payload = [
        {
            "app": str(app),
            "name": str(name),
            "applied": applied.isoformat() if hasattr(applied, "isoformat") else str(applied),
        }
        for app, name, applied in rows
    ]
    destination.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return {"migration_count": len(payload)}


def write_api_route_inventory(resolver, destination: Path) -> dict:
    rows: list[dict[str, str]] = []

    def walk(patterns, prefix=""):
        for entry in patterns:
            route = prefix + str(entry.pattern)
            children = getattr(entry, "url_patterns", None)
            if children is not None:
                walk(children, route)
                continue
            callback = getattr(entry, "callback", None)
            view_name = ""
            if callback is not None:
                module = getattr(callback, "__module__", "")
                name = getattr(callback, "__name__", callback.__class__.__name__)
                view_name = f"{module}.{name}" if module else name
            rows.append(
                {
                    "route": route,
                    "name": str(getattr(entry, "name", "") or ""),
                    "view": view_name,
                }
            )

    walk(resolver.url_patterns)
    rows.sort(key=lambda row: (row["route"], row["name"], row["view"]))
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=["route", "name", "view"])
        writer.writeheader()
        writer.writerows(rows)
    return {"route_count": len(rows)}


def write_runtime_configuration(settings, connection, destination: Path) -> dict:
    database = settings.DATABASES["default"]
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "database": {
            "engine": str(database.get("ENGINE", "")),
            "vendor": str(connection.vendor),
            "name": str(database.get("NAME", "")),
            "host": str(database.get("HOST", "")),
            "port": str(database.get("PORT", "")),
        },
        "application": {
            "time_zone": str(getattr(settings, "TIME_ZONE", "")),
            "language_code": str(getattr(settings, "LANGUAGE_CODE", "")),
            "allowed_hosts": list(getattr(settings, "ALLOWED_HOSTS", [])),
            "csrf_trusted_origins": list(getattr(settings, "CSRF_TRUSTED_ORIGINS", [])),
            "installed_apps": [str(value) for value in getattr(settings, "INSTALLED_APPS", [])],
        },
        "security": {
            "secrets_included": False,
            "secret_material_must_be_reissued_at_destination": True,
            "excluded_secret_classes": [
                "database password",
                "Django SECRET_KEY",
                "Redis password",
                "field-encryption keys",
                "backup encryption key",
                "ticket/signing keys",
                "third-party access tokens",
            ],
        },
    }
    destination.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return payload




def write_configuration_catalog(connection, csv_path: Path, json_path: Path) -> dict:
    """Index rule/config/mapping/cycle tables without duplicating the full SQL dump."""
    keywords = ("rule", "config", "setting", "policy", "mapping", "cycle", "dictionary")
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT TABLE_NAME FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_TYPE = 'BASE TABLE' "
            "ORDER BY TABLE_NAME"
        )
        table_names = [str(row[0]) for row in cursor.fetchall()]
    rows = []
    for table_name in table_names:
        lowered = table_name.lower()
        matched = [keyword for keyword in keywords if keyword in lowered]
        if not matched:
            continue
        escaped = table_name.replace("`", "``")
        with connection.cursor() as cursor:
            cursor.execute(f"SELECT COUNT(*) FROM `{escaped}`")
            row_count = int(cursor.fetchone()[0])
        rows.append(
            {
                "table_name": table_name,
                "category": ",".join(matched),
                "row_count": row_count,
                "content_location": "database.sql",
            }
        )
    fields = ["table_name", "category", "row_count", "content_location"]
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    json_path.write_text(
        json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return {"configuration_table_count": len(rows)}


def write_interface_mapping_catalog(connection, destination: Path) -> dict:
    """Export non-secret HR18 target field mappings as human-readable JSON."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT COUNT(*) FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA = DATABASE() "
            "AND TABLE_NAME = 'hr18_exchange_target_mapping_version'"
        )
        exists = int(cursor.fetchone()[0]) > 0
        if not exists:
            rows = []
        else:
            cursor.execute(
                "SELECT tenant_id, target_code, version_no, status, dataset_code, "
                "dataset_version, transport_kind, provider_key, mapping_json, "
                "expected_receipt, content_hash "
                "FROM hr18_exchange_target_mapping_version "
                "ORDER BY tenant_id, target_code, version_no"
            )
            raw_rows = cursor.fetchall()
            rows = []
            for raw in raw_rows:
                mapping = raw[8]
                if isinstance(mapping, str):
                    try:
                        mapping = json.loads(mapping)
                    except json.JSONDecodeError:
                        mapping = {"raw": mapping}
                rows.append(
                    {
                        "tenant_id": str(raw[0]),
                        "target_code": str(raw[1]),
                        "version_no": int(raw[2]),
                        "status": str(raw[3]),
                        "dataset_code": str(raw[4]),
                        "dataset_version": int(raw[5]),
                        "transport_kind": str(raw[6]),
                        "provider_key": str(raw[7]),
                        "mapping": mapping,
                        "expected_receipt": bool(raw[9]),
                        "content_hash": str(raw[10] or ""),
                    }
                )
    destination.write_text(
        json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return {"interface_mapping_version_count": len(rows)}

def write_secret_handover_requirements(settings, destination: Path) -> dict:
    raw_keys = str(getattr(settings, "FIELD_ENCRYPTION_KEYS", "") or "").strip()
    key_ids = []
    for entry in raw_keys.split(","):
        entry = entry.strip()
        if not entry:
            continue
        key_id, separator, _material = entry.partition(":")
        if separator and key_id:
            key_ids.append(key_id)
    payload = {
        "contains_secret_values": False,
        "requirements": [
            {
                "name": "FIELD_ENCRYPTION_KEYS",
                "disposition": "TRANSFER_SEPARATELY",
                "reason": "Required to decrypt sensitive database fields already present in database.sql.",
                "format": "key-id:Fernet-key keyring",
                "configured_key_ids": key_ids,
            },
            {
                "name": "FIELD_FINGERPRINT_KEY",
                "disposition": "TRANSFER_SEPARATELY_OR_CONTROLLED_REINDEX",
                "reason": "Existing exact-match fingerprints depend on this key.",
            },
            {
                "name": "SECRET_KEY",
                "disposition": "REISSUE_AT_DESTINATION",
                "reason": "Do not transfer the running Django secret in the data package; new deployment may invalidate old sessions.",
            },
            {
                "name": "HR08_TICKET_SIGNING_KEY",
                "disposition": "REISSUE_AT_DESTINATION",
                "reason": "Short-lived download tickets must not bind a new operator to the old signing key.",
            },
            {
                "name": "PRODUCTION_BACKUP_ENCRYPTION_KEY",
                "disposition": "TRANSFER_ONLY_IF_LEGACY_BACKUPS_ARE_PART_OF_HANDOVER",
                "reason": "Not needed to restore this open-format handover package.",
            },
            {
                "name": "THIRD_PARTY_CREDENTIALS",
                "disposition": "ROTATE_OR_REISSUE",
                "reason": "SSO/data-platform/provincial-platform/database/SMTP credentials should be reissued by the school/system owner.",
            },
        ],
        "policy": (
            "Secret values are intentionally excluded from the open data package. "
            "Keys required to interpret encrypted school data must be handed over through "
            "a separate school-controlled secret channel; this avoids both plaintext secret "
            "leakage and vendor lock-in."
        ),
    }
    destination.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return payload

def append_receipt(root: Path, event: dict) -> Path:
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    os.chmod(root, 0o700)
    path = root / "school-handover-receipts.jsonl"
    line = json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n"
    descriptor = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        os.write(descriptor, line.encode("utf-8"))
    finally:
        os.close(descriptor)
    os.chmod(path, 0o600)
    return path
