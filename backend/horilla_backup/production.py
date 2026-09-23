"""Encrypted, integrity-checked production backup primitives."""

from __future__ import annotations

import hashlib
import json
import re
import stat
import os
import tempfile
from pathlib import Path

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


MAGIC = b"RHRB1"
NONCE_BYTES = 12
TAG_BYTES = 16
CHUNK_BYTES = 1024 * 1024


class ProductionBackupError(RuntimeError):
    pass


def _key(secret: str) -> bytes:
    raw = str(secret or "").encode("utf-8")
    if len(raw) < 32 or str(secret).lower().startswith("change-me"):
        raise ProductionBackupError(
            "PRODUCTION_BACKUP_ENCRYPTION_KEY must contain at least 32 non-placeholder bytes"
        )
    return hashlib.sha256(raw).digest()


def sha256_file(path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        while chunk := source.read(CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def _temporary_destination(destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    os.close(descriptor)
    os.chmod(name, 0o600)
    return Path(name)


def encrypt_file(source, destination, secret: str) -> Path:
    source = Path(source)
    destination = Path(destination)
    temporary = _temporary_destination(destination)
    nonce = os.urandom(NONCE_BYTES)
    encryptor = Cipher(algorithms.AES(_key(secret)), modes.GCM(nonce)).encryptor()
    try:
        with source.open("rb") as input_file, temporary.open("wb") as output_file:
            output_file.write(MAGIC)
            output_file.write(nonce)
            while chunk := input_file.read(CHUNK_BYTES):
                output_file.write(encryptor.update(chunk))
            output_file.write(encryptor.finalize())
            output_file.write(encryptor.tag)
        os.replace(temporary, destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return destination


def decrypt_file(source, destination, secret: str) -> Path:
    source = Path(source)
    destination = Path(destination)
    minimum_size = len(MAGIC) + NONCE_BYTES + TAG_BYTES
    if not source.is_file() or source.stat().st_size <= minimum_size:
        raise ProductionBackupError("Encrypted backup artifact is missing or truncated")

    with source.open("rb") as input_file:
        if input_file.read(len(MAGIC)) != MAGIC:
            raise ProductionBackupError("Encrypted backup artifact has an unknown format")
        nonce = input_file.read(NONCE_BYTES)
        input_file.seek(-TAG_BYTES, os.SEEK_END)
        tag = input_file.read(TAG_BYTES)

    ciphertext_bytes = source.stat().st_size - minimum_size
    temporary = _temporary_destination(destination)
    decryptor = Cipher(algorithms.AES(_key(secret)), modes.GCM(nonce, tag)).decryptor()
    try:
        with source.open("rb") as input_file, temporary.open("wb") as output_file:
            input_file.seek(len(MAGIC) + NONCE_BYTES)
            remaining = ciphertext_bytes
            while remaining:
                chunk = input_file.read(min(CHUNK_BYTES, remaining))
                if not chunk:
                    raise ProductionBackupError("Encrypted artifact ended unexpectedly")
                remaining -= len(chunk)
                output_file.write(decryptor.update(chunk))
            output_file.write(decryptor.finalize())
        os.replace(temporary, destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return destination


def resolve_bundle(backup_root, bundle_name: str) -> Path:
    root = Path(backup_root).resolve()
    candidate = (root / str(bundle_name)).resolve()
    if candidate.parent != root or not candidate.is_dir():
        raise ProductionBackupError("Backup bundle must be an existing direct child of BACKUP_ROOT")
    return candidate


BACKUP_ARTIFACT_NAMES = frozenset({"database.sql.enc", "media.tar.gz.enc"})


def _unique_json_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ProductionBackupError("Backup manifest has duplicate fields")
        result[key] = value
    return result


def verified_bundle_manifest(bundle: Path) -> dict:
    """Only the two artifacts created by create_production_backup are accepted.

    A hash in a manifest does not authorize a path outside the bundle. AES-GCM
    authentication is still checked by decrypt_file before any SQL is run.
    """
    bundle = Path(bundle)
    manifest_path = bundle / "manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file() or manifest_path.stat().st_size > 1024 * 1024:
        raise ProductionBackupError("Backup manifest must be a bounded regular file")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"), object_pairs_hook=_unique_json_pairs)
    except (OSError, ValueError) as exc:
        raise ProductionBackupError("Invalid backup manifest") from exc
    if not isinstance(manifest, dict) or manifest.get("format") != "renshi-production-backup-v1":
        raise ProductionBackupError("unsupported backup manifest format")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict) or set(artifacts) != BACKUP_ARTIFACT_NAMES:
        raise ProductionBackupError("Backup must contain exactly the database and media encrypted artifacts")
    for name, metadata in artifacts.items():
        verified_bundle_artifact(bundle, manifest, name)
    return manifest


def verified_bundle_artifact(bundle: Path, manifest: dict, name: str) -> Path:
    if name not in BACKUP_ARTIFACT_NAMES:
        raise ProductionBackupError("Unexpected backup artifact name")
    metadata = manifest.get("artifacts", {}).get(name)
    if not isinstance(metadata, dict) or type(metadata.get("bytes")) is not int or metadata["bytes"] <= len(MAGIC) + NONCE_BYTES + TAG_BYTES:
        raise ProductionBackupError("Invalid encrypted artifact metadata")
    expected = metadata.get("sha256")
    if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", expected):
        raise ProductionBackupError("Invalid encrypted artifact digest")
    artifact = Path(bundle) / name
    if artifact.is_symlink() or not artifact.is_file() or not stat.S_ISREG(artifact.stat().st_mode):
        raise ProductionBackupError("Backup artifacts must be regular, non-link files")
    if artifact.stat().st_size != metadata["bytes"] or sha256_file(artifact).lower() != expected.lower():
        raise ProductionBackupError("Backup artifact content or size mismatch")
    return artifact
