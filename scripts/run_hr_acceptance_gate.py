#!/usr/bin/env python3
"""Run the production-shaped HR01-HR18 acceptance gate in an isolated project.

Safety properties:
- never reads or writes the deployment `.env`;
- generates a temporary acceptance-only env file and random credentials;
- refuses project names that could plausibly be production;
- uses a unique Docker Compose project/volume namespace;
- restores backups only into a separate database;
- tears down its own containers/volumes unless --keep is explicitly requested.

This is a pre-production acceptance harness. It does not deploy or modify a
real production server.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIN_COMPOSE = (2, 24, 4)
PRODUCTION_NAME_RE = re.compile(r"(^|[-_])prod([-_]|$)", re.I)
PROJECT_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{2,62}$")

HR_TEST_APPS = (
    "base",
    "hr_control_center",
    "hr_structure",
    "hr_staff",
    "hr_recruitment",
    "hr_onboarding",
    "hr_changes",
    "hr_contracts",
    "hr_external",
    "hr_qualification",
    "hr10_development",
    "hr_time",
    "hr_assessment",
    "hr_title",
    "hr_appointment",
    "hr_payroll",
    "hr_exit",
    "hr_self",
    "hr_data",
)


class AcceptanceGateError(RuntimeError):
    pass


@dataclass(frozen=True)
class RuntimePaths:
    root: Path
    env_file: Path
    backup_root: Path
    evidence_file: Path
    handover_root: Path | None = None
    handover_audit_root: Path | None = None


def _secret_hex(nbytes: int = 24) -> str:
    return secrets.token_hex(nbytes)


def _fernet_key() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii")


def _validate_project_name(project: str) -> str:
    project = str(project or "").strip().lower()
    if not PROJECT_RE.fullmatch(project):
        raise AcceptanceGateError(
            "acceptance project must be 3-63 lowercase letters/digits/_/-"
        )
    if (
        PRODUCTION_NAME_RE.search(project)
        or "production" in project
        or "live" in project
    ):
        raise AcceptanceGateError(
            "refusing a project name containing prod/production/live"
        )
    if "acceptance" not in project and "qa" not in project:
        raise AcceptanceGateError(
            "acceptance project name must contain 'acceptance' or 'qa'"
        )
    return project


def _version_tuple(raw: str) -> tuple[int, int, int]:
    match = re.search(r"(?<!\d)(\d+)\.(\d+)\.(\d+)(?!\d)", str(raw or ""))
    if not match:
        raise AcceptanceGateError(f"cannot parse Docker Compose version: {raw!r}")
    return tuple(int(part) for part in match.groups())


def _runtime_paths(project: str) -> RuntimePaths:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    root = ROOT / ".runtime" / "acceptance" / f"{project}-{stamp}-{os.getpid()}"
    return RuntimePaths(
        root=root,
        env_file=root / "acceptance.env",
        backup_root=root / "backups",
        handover_root=root / "handover",
        handover_audit_root=root / "handover-audit",
        evidence_file=ROOT / "docs" / "reports" / "acceptance_evidence" / f"{project}-{stamp}-{os.getpid()}.json",
    )


def _build_runtime_env(paths: RuntimePaths) -> dict[str, str]:
    mysql_password = _secret_hex(24)
    mysql_root_password = _secret_hex(24)
    redis_password = _secret_hex(24)
    return {
        "HR_ACCEPTANCE_ISOLATED": "YES",
        "HR_ACCEPTANCE_IMAGE": "yueke-hr-acceptance:" + _secret_hex(12),
        "HR_ACCEPTANCE_ENV_FILE": str(paths.env_file),
        "DEBUG": "0",
        "HORILLA_ENV": "production",
        "SECRET_KEY": secrets.token_urlsafe(64),
        "ALLOWED_HOSTS": "acceptance.local",
        "CSRF_TRUSTED_ORIGINS": "https://acceptance.local",
        "MYSQL_DATABASE": "renshi_db",
        "MYSQL_USER": "renshi_user",
        "MYSQL_PASSWORD": mysql_password,
        "MYSQL_ROOT_PASSWORD": mysql_root_password,
        "DATABASE_URL": f"mysql://renshi_user:{mysql_password}@db:3306/renshi_db",
        "DB_INIT_PASSWORD": _secret_hex(32),
        "REDIS_PASSWORD": redis_password,
        "REDIS_URL": f"redis://:{redis_password}@redis:6379/0",
        "PRODUCTION_BACKUP_ENCRYPTION_KEY": secrets.token_urlsafe(48),
        "PRODUCTION_BACKUP_RETENTION_COUNT": "3",
        "PRODUCTION_BACKUP_INTERVAL_HOURS": "24",
        "BACKUP_STORAGE_PATH": str(paths.backup_root),
        "HANDOVER_STORAGE_PATH": str(paths.handover_root or (paths.root / "handover")),
        "HANDOVER_AUDIT_STORAGE_PATH": str(
            paths.handover_audit_root or (paths.root / "handover-audit")
        ),
        "COMPANY_SCOPED_PERMISSIONS": "True",
        "TENANT_FAIL_CLOSED": "True",
        "SECURE_SSL_REDIRECT": "1",
        "SECURE_HSTS_SECONDS": "31536000",
        "FAIL2BAN_MAX_RETRY": "5",
        "FAIL2BAN_IP_MAX_RETRY": "60",
        "FAIL2BAN_ATTEMPT_WINDOW": "900",
        "FAIL2BAN_BAN_TIME": "900",
        "LOGIN_REMEMBER_ME_SECONDS": "86400",
        "TWO_FACTORS_AUTHENTICATION": "True",
        "MFA_OTP_TTL_SECONDS": "300",
        "MFA_OTP_MAX_ATTEMPTS": "5",
        "MFA_OTP_RESEND_COOLDOWN_SECONDS": "60",
        # Acceptance exercises the production configuration gate but does not
        # send real mail. No public SMTP account or production secret is used.
        "EMAIL_HOST": "smtp.acceptance.internal",
        "EMAIL_PORT": "587",
        "EMAIL_HOST_USER": "acceptance-smtp-user",
        "EMAIL_HOST_PASSWORD": _secret_hex(24),
        "EMAIL_USE_TLS": "True",
        "EMAIL_USE_SSL": "False",
        "EMAIL_TIMEOUT": "10",
        "EMAIL_FAIL_SILENTLY": "False",
        "DEFAULT_FROM_EMAIL": "no-reply@acceptance.local",
        "HR04_PRIVACY_NOTICE_VERSION": "ACCEPTANCE-2026",
        "HR04_CANDIDATE_RETENTION_DAYS": "365",
        "HR04_PRIVACY_CONTACT": "privacy@acceptance.local",
        "HR04_APPLICATION_MATERIAL_MAX_BYTES": "20971520",
        "FIELD_ENCRYPTION_KEYS": f"acceptance:{_fernet_key()}",
        "FIELD_FINGERPRINT_KEY": _secret_hex(32),
        "HR08_TICKET_SIGNING_KEY": _secret_hex(32),
        "MALWARE_SCAN_REQUIRED": "True",
        "MALWARE_SCAN_HOST": "clamav",
        "MALWARE_SCAN_PORT": "3310",
        "MALWARE_SCAN_TIMEOUT_SECONDS": "10",
        "MALWARE_SCAN_MAX_BYTES": "52428800",
        "REQUIRED_EXTERNAL_INTEGRATIONS": "",
        "LOG_FORMAT": "json",
        "LOG_LEVEL": "WARNING",
    }


def isolated_child_env(values: dict[str, str]) -> dict[str, str]:
    """Do not let shell exports override generated Compose interpolation values.

    No inherited DATABASE_URL, SMTP/token, DJANGO_SETTINGS_MODULE, COMPOSE_FILE,
    DOCKER_HOST or DOCKER_CONTEXT. A remote context is separately refused.
    """
    allowed = {
        "PATH", "HOME", "USERPROFILE", "SYSTEMROOT", "SystemRoot", "WINDIR",
        "TEMP", "TMP", "TMPDIR", "USER", "LOGNAME", "LANG", "LC_ALL",
        "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE",
        "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "no_proxy",
    }
    result = {k: v for k, v in os.environ.items() if k in allowed}
    result.update(values)
    # Explicit env-file in every command is required even when interpolation
    # variables are passed here. Never ask Compose to discover a project .env.
    result["COMPOSE_DISABLE_ENV_FILE"] = "1"
    return result


def assert_local_docker(env: dict[str, str]) -> None:
    result = _run(["docker", "context", "inspect"], env=env, capture=True, timeout=30)
    contexts = json.loads(result.stdout)
    endpoint = contexts[0]["Endpoints"]["docker"]["Host"]
    if not (endpoint.startswith("unix://") or endpoint.startswith("npipe://")):
        raise AcceptanceGateError("acceptance requires a local Docker socket; remote contexts are refused")


def assert_unused_project(project: str, env: dict[str, str]) -> None:
    """Refuse adoption/deletion of an existing namespace, even one named qa."""
    label = f"label=com.docker.compose.project={project}"
    for args in (("ps", "-aq"), ("volume", "ls", "-q"), ("network", "ls", "-q")):
        result = _run(["docker", *args, "--filter", label], env=env, capture=True, timeout=30)
        if result.stdout.strip():
            raise AcceptanceGateError("acceptance namespace already owns resources; choose a new name")


def _write_env(path: Path, values: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for key, value in sorted(values.items()):
        if "\n" in value or "\r" in value:
            raise AcceptanceGateError(f"unsafe newline in generated value for {key}")
        lines.append(f"{key}={value}")
    # Create owner-only from the first byte; do not follow/overwrite old files.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write("\n".join(lines) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def _display_command(command: list[str]) -> str:
    redacted = []
    for token in command:
        upper = token.upper()
        if "PASSWORD=" in upper or "SECRET=" in upper or "TOKEN=" in upper:
            key = token.split("=", 1)[0]
            redacted.append(f"{key}=<redacted>")
        elif token.startswith("-p") and len(token) > 2:
            redacted.append("-p<redacted>")
        elif re.search(r"(mysql|redis)://[^ ]+:[^ @]+@", token, re.I):
            redacted.append(re.sub(r"((?:mysql|redis)://[^: ]+:)[^@ ]+(@)", r"\1<redacted>\2", token, flags=re.I))
        else:
            redacted.append(token)
    return shlex.join(redacted)


def _run(command: list[str], *, env=None, capture=False, timeout=None) -> subprocess.CompletedProcess:
    print("+", _display_command(command), flush=True)
    return subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        check=True,
        text=True,
        capture_output=capture,
        timeout=timeout,
    )


def _compose_base(project: str, env_file: Path) -> list[str]:
    return [
        "docker",
        "compose",
        "--env-file",
        str(env_file),
        "-p",
        project,
        "-f",
        "docker-compose.yml",
        "-f",
        "docker-compose.prod.yml",
        "-f",
        "docker-compose.acceptance.yml",
    ]


def _phase(evidence: dict, name: str, command: list[str], *, env=None, capture=False):
    started = time.monotonic()
    try:
        result = _run(command, env=env, capture=capture)
    except Exception as exc:
        evidence["phases"].append(
            {"name": name, "status": "FAILED", "seconds": round(time.monotonic() - started, 3)}
        )
        raise AcceptanceGateError(f"{name} failed") from exc
    evidence["phases"].append(
        {"name": name, "status": "PASSED", "seconds": round(time.monotonic() - started, 3)}
    )
    return result


def _redacted_plan(project: str) -> list[str]:
    return [
        f"isolated compose project: {project}",
        "generate temporary acceptance-only secrets/env (never use .env)",
        "validate Docker Compose >= 2.24.4 and merged config",
        "start isolated MySQL 8.4 + Redis + ClamAV",
        "run production release entrypoint (migrate + collectstatic)",
        "run check --deploy + makemigrations --check + migrate --check",
        "verify all governed HR sensitive fields use the current encryption/fingerprint keys",
        "run HR01-HR18 Django/MySQL test suite",
        "bootstrap an acceptance-only first school/admin",
        "export a secret-free school initialization snapshot (roles/config/mappings/migrations)",
        "create + cryptographically verify an encrypted MySQL/media backup",
        "restore backup into a separate renshi_restore_test database",
        "run migrate --check against restored database and compare schema table counts",
        "create + manifest/SHA verify an open-format school handover package",
        "restore handover package into a second separate renshi_handover_restore_test database",
        "run migrate --check and compare schema table counts for the handover-restored database",
        "start web and verify /ready/ returns HTTP 200 inside the container",
        "optionally build the final procurement evidence package from real performance/trial/training/remediation/integration evidence",
        "destroy only this acceptance project and its volumes",
    ]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--project",
        default=f"yueke_hr_acceptance_{os.getpid()}",
        help="isolated Compose project prefix; must contain acceptance or qa; random suffix always added",
    )
    parser.add_argument("--plan", action="store_true", help="print the safe execution plan only")
    parser.add_argument(
        "--keep",
        action="store_true",
        help="keep acceptance containers/volumes for debugging (never for production)",
    )
    parser.add_argument("--procurement-pack-output", help="final procurement acceptance evidence ZIP")
    parser.add_argument("--procurement-performance-json", help="real QA performance evidence from run_procurement_performance_probe.py")
    parser.add_argument("--trial-run-record", help="machine-verifiable trial-run JSON")
    parser.add_argument("--remediation-register", help="closed remediation CSV")
    parser.add_argument("--training-record", help="administrator/operator training CSV")
    parser.add_argument("--external-integration-record", help="external integration acceptance JSON")
    args = parser.parse_args(argv)

    try:
        project = _validate_project_name(args.project)
    except AcceptanceGateError as exc:
        print(f"HR_ACCEPTANCE_GATE_REFUSED: {exc}", file=sys.stderr)
        return 2

    if args.plan:
        print("HR_ACCEPTANCE_GATE_PLAN")
        for step in _redacted_plan(project):
            print(f"- {step}")
        return 0

    # --project is a prefix. Concurrent runs must never share the same resources.
    project = project[:49] + "_" + _secret_hex(6)
    paths = _runtime_paths(project)
    values = _build_runtime_env(paths)
    bootstrap_password = "Aa9!" + _secret_hex(20)
    paths.backup_root.mkdir(parents=True, exist_ok=True)
    (paths.handover_root or (paths.root / "handover")).mkdir(parents=True, exist_ok=True)
    (paths.handover_audit_root or (paths.root / "handover-audit")).mkdir(
        parents=True, exist_ok=True
    )
    paths.evidence_file.parent.mkdir(parents=True, exist_ok=True)
    _write_env(paths.env_file, values)

    evidence = {
        "schemaVersion": 1,
        "gate": "HR01-HR18 isolated production-shaped acceptance",
        "project": project,
        "startedAt": datetime.now(timezone.utc).isoformat(),
        "status": "RUNNING",
        "phases": [],
        "productionTouched": False,
        "gitHubTouched": False,
    }
    compose = _compose_base(project, paths.env_file)
    child_env = isolated_child_env(values)
    owns_project = False

    try:
        version = _phase(
            evidence,
            "compose-version",
            ["docker", "compose", "version", "--short"],
            env=child_env,
            capture=True,
        )
        parsed = _version_tuple(version.stdout or version.stderr)
        if parsed < MIN_COMPOSE:
            raise AcceptanceGateError(
                "Docker Compose >= 2.24.4 is required by !override overlays"
            )

        assert_local_docker(child_env)
        assert_unused_project(project, child_env)
        owns_project = True
        _phase(evidence, "compose-config", [*compose, "config", "--quiet"], env=child_env)
        _phase(evidence, "image-build", [*compose, "build", "release"], env=child_env)
        _phase(
            evidence,
            "infrastructure",
            [*compose, "up", "-d", "--wait", "db", "redis", "clamav"],
            env=child_env,
        )
        _phase(
            evidence,
            "release",
            [*compose, "run", "--rm", "--no-deps", "release"],
            env=child_env,
        )
        _phase(
            evidence,
            "django-check-deploy",
            [*compose, "run", "--rm", "--no-deps", "web", "python", "manage.py", "check", "--deploy"],
            env=child_env,
        )
        _phase(
            evidence,
            "migration-drift",
            [*compose, "run", "--rm", "--no-deps", "web", "python", "manage.py", "makemigrations", "--check", "--dry-run"],
            env=child_env,
        )
        _phase(
            evidence,
            "migration-applied",
            [*compose, "run", "--rm", "--no-deps", "web", "python", "manage.py", "migrate", "--check"],
            env=child_env,
        )
        _phase(
            evidence,
            "field-security-check",
            [
                *compose, "run", "--rm", "--no-deps", "web",
                "python", "manage.py", "rotate_hr_field_security", "--check",
            ],
            env=child_env,
        )
        _phase(
            evidence,
            "hr01-hr18-tests",
            [
                *compose,
                "run", "--rm", "--no-deps", "web",
                "python", "manage.py", "test", *HR_TEST_APPS,
                "--noinput", "--verbosity", "1",
            ],
            env=child_env,
        )
        bootstrap_env = child_env.copy()
        bootstrap_env["HR_BOOTSTRAP_ADMIN_PASSWORD"] = bootstrap_password
        _phase(
            evidence,
            "bootstrap-first-admin",
            [
                *compose,
                "run", "--rm", "--no-deps",
                "-e", "HR_BOOTSTRAP_ADMIN_PASSWORD",
                "web", "python", "manage.py", "bootstrap_production_admin",
                "--username", "acceptance-admin",
                "--email", "acceptance-admin@acceptance.local",
                "--first-name", "验收",
                "--last-name", "管理员",
                "--phone", "13800000000",
                "--company-name", "跃科高校人事验收学校",
                "--company-address", "Acceptance isolated environment",
                "--company-country", "CN",
                "--company-state", "Hunan",
                "--company-city", "Changsha",
                "--company-zip", "410000",
            ],
            env=bootstrap_env,
        )

        initialization_name = "school-initialization-snapshot.json"
        initialization = _phase(
            evidence,
            "school-initialization-snapshot",
            [
                *compose, "run", "--rm", "--no-deps",
                "backup-scheduler", "python", "manage.py", "export_school_initialization_snapshot",
                "--output", f"/app/handover/{initialization_name}",
                "--operator", "acceptance-gate",
            ],
            env=child_env,
            capture=True,
        )
        init_match = re.search(r"SCHOOL_INITIALIZATION_SNAPSHOT_OK path=(.+?) sha256=([0-9a-f]{64})", initialization.stdout or "")
        if not init_match:
            raise AcceptanceGateError("initialization snapshot command did not return path + sha256")
        initialization_snapshot_host = (paths.handover_root or (paths.root / "handover")) / initialization_name
        if not initialization_snapshot_host.is_file():
            raise AcceptanceGateError("initialization snapshot is not visible in the persisted handover volume")
        evidence["initializationSnapshot"] = initialization_name
        evidence["initializationSnapshotSha256"] = init_match.group(2)

        backup = _phase(
            evidence,
            "backup-create",
            [*compose, "run", "--rm", "--no-deps", "backup-scheduler", "python", "manage.py", "create_production_backup"],
            env=child_env,
            capture=True,
        )
        match = re.search(r"PRODUCTION_BACKUP_OK bundle=(.+)", backup.stdout or "")
        if not match:
            raise AcceptanceGateError("backup command did not return a bundle path")
        bundle_name = Path(match.group(1).strip()).name
        evidence["backupBundle"] = bundle_name
        _phase(
            evidence,
            "backup-verify",
            [*compose, "run", "--rm", "--no-deps", "backup-scheduler", "python", "manage.py", "verify_production_backup", bundle_name],
            env=child_env,
        )

        root_password = values["MYSQL_ROOT_PASSWORD"]
        _phase(
            evidence,
            "restore-target-create",
            [
                *compose, "exec", "-T", "db", "sh", "-lc",
                "MYSQL_PWD=\"$MYSQL_ROOT_PASSWORD\" mysql -uroot --execute=\"DROP DATABASE IF EXISTS renshi_restore_test; CREATE DATABASE renshi_restore_test CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;\"",
            ],
            env=child_env,
        )
        restore_env = child_env.copy()
        restore_env.update({
            "RESTORE_DATABASE_USER": "root",
            "RESTORE_DATABASE_PASSWORD": root_password,
            "RESTORE_DATABASE_HOST": "db",
        })
        _phase(
            evidence,
            "backup-restore",
            [
                *compose, "run", "--rm", "--no-deps",
                "-e", "RESTORE_DATABASE_USER",
                "-e", "RESTORE_DATABASE_PASSWORD",
                "-e", "RESTORE_DATABASE_HOST",
                "backup-scheduler", "python", "manage.py", "restore_production_backup",
                bundle_name,
                "--target-database", "renshi_restore_test",
                "--confirm-target", "renshi_restore_test",
            ],
            env=restore_env,
        )
        restored_env = child_env.copy()
        restored_env["DATABASE_URL"] = f"mysql://root:{root_password}@db:3306/renshi_restore_test"
        _phase(
            evidence,
            "restored-migration-check",
            [
                *compose, "run", "--rm", "--no-deps",
                "-e", "DATABASE_URL",
                "web", "python", "manage.py", "migrate", "--check",
            ],
            env=restored_env,
        )
        counts = _phase(
            evidence,
            "restore-schema-count",
            [
                *compose, "exec", "-T", "db", "sh", "-lc",
                "MYSQL_PWD=\"$MYSQL_ROOT_PASSWORD\" mysql -uroot --batch --skip-column-names --execute=\"SELECT table_schema, COUNT(*) FROM information_schema.tables WHERE table_schema IN ('renshi_db','renshi_restore_test') GROUP BY table_schema ORDER BY table_schema;\"",
            ],
            env=child_env,
            capture=True,
        )
        parsed_counts = {}
        for line in (counts.stdout or "").splitlines():
            parts = line.split("\t")
            if len(parts) == 2 and parts[1].isdigit():
                parsed_counts[parts[0]] = int(parts[1])
        if (
            parsed_counts.get("renshi_db", 0) <= 0
            or parsed_counts.get("renshi_db") != parsed_counts.get("renshi_restore_test")
        ):
            raise AcceptanceGateError(
                f"restored schema table count mismatch: {parsed_counts}"
            )
        evidence["schemaTableCounts"] = parsed_counts

        handover = _phase(
            evidence,
            "handover-create",
            [
                *compose, "run", "--rm", "--no-deps",
                "backup-scheduler", "python", "manage.py", "create_school_handover_package",
                "--recipient", "acceptance-school-owner",
                "--purpose", "isolated portability acceptance",
                "--operator", "acceptance-gate",
                "--confirm-sensitive-export",
                "I_UNDERSTAND_THIS_EXPORT_CONTAINS_SENSITIVE_HR_DATA",
            ],
            env=child_env,
            capture=True,
        )
        handover_match = re.search(
            r"SCHOOL_HANDOVER_OK package=(.+?) sha256=([0-9a-f]{64})",
            handover.stdout or "",
        )
        if not handover_match:
            raise AcceptanceGateError("handover command did not return package + sha256")
        handover_name = Path(handover_match.group(1).strip()).name
        handover_sha256 = handover_match.group(2)
        evidence["handoverPackage"] = handover_name
        evidence["handoverSha256"] = handover_sha256
        handover_verify = _phase(
            evidence,
            "handover-verify",
            [
                *compose, "run", "--rm", "--no-deps",
                "backup-scheduler", "python", "manage.py", "verify_school_handover_package",
                handover_name, "--operator", "acceptance-gate",
            ],
            env=child_env,
            capture=True,
        )
        verified_match = re.search(
            r"SCHOOL_HANDOVER_VERIFIED package=(.+?) sha256=([0-9a-f]{64})",
            handover_verify.stdout or "",
        )
        if not verified_match or verified_match.group(2) != handover_sha256:
            raise AcceptanceGateError(
                "handover verify SHA-256 does not match the created package digest"
            )
        _phase(
            evidence,
            "handover-restore-target-create",
            [
                *compose, "exec", "-T", "db", "sh", "-lc",
                'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot --execute="DROP DATABASE IF EXISTS renshi_handover_restore_test; CREATE DATABASE renshi_handover_restore_test CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;"',
            ],
            env=child_env,
        )
        _phase(
            evidence,
            "handover-restore",
            [
                *compose, "run", "--rm", "--no-deps",
                "-e", "RESTORE_DATABASE_USER",
                "-e", "RESTORE_DATABASE_PASSWORD",
                "-e", "RESTORE_DATABASE_HOST",
                "backup-scheduler", "python", "manage.py", "restore_school_handover_package",
                handover_name,
                "--target-database", "renshi_handover_restore_test",
                "--confirm-target", "renshi_handover_restore_test",
                "--media-target", "/tmp/renshi-handover-media",
                "--operator", "acceptance-gate",
                "--confirm-restore-policy", "RESTORE_TO_EMPTY_DATABASE_ONLY",
            ],
            env=restore_env,
        )
        handover_restored_env = child_env.copy()
        handover_restored_env["DATABASE_URL"] = (
            f"mysql://root:{root_password}@db:3306/renshi_handover_restore_test"
        )
        _phase(
            evidence,
            "handover-restored-migration-check",
            [
                *compose, "run", "--rm", "--no-deps",
                "-e", "DATABASE_URL",
                "web", "python", "manage.py", "migrate", "--check",
            ],
            env=handover_restored_env,
        )
        handover_counts = _phase(
            evidence,
            "handover-restore-schema-count",
            [
                *compose, "exec", "-T", "db", "sh", "-lc",
                "MYSQL_PWD=\"$MYSQL_ROOT_PASSWORD\" mysql -uroot --batch --skip-column-names --execute=\"SELECT table_schema, COUNT(*) FROM information_schema.tables WHERE table_schema IN ('renshi_db','renshi_handover_restore_test') GROUP BY table_schema ORDER BY table_schema;\"",
            ],
            env=child_env,
            capture=True,
        )
        parsed_handover_counts = {}
        for line in (handover_counts.stdout or "").splitlines():
            parts = line.split("\t")
            if len(parts) == 2 and parts[1].isdigit():
                parsed_handover_counts[parts[0]] = int(parts[1])
        if (
            parsed_handover_counts.get("renshi_db", 0) <= 0
            or parsed_handover_counts.get("renshi_db")
            != parsed_handover_counts.get("renshi_handover_restore_test")
        ):
            raise AcceptanceGateError(
                f"handover-restored schema table count mismatch: {parsed_handover_counts}"
            )
        evidence["handoverSchemaTableCounts"] = parsed_handover_counts

        _phase(evidence, "web-start", [*compose, "up", "-d", "--wait", "web"], env=child_env)
        _phase(
            evidence,
            "ready-endpoint",
            [
                *compose, "exec", "-T", "web", "python", "-c",
                (
                    "import urllib.request; "
                    "r=urllib.request.Request('http://127.0.0.1:8000/ready/',headers={'Host':'acceptance.local','X-Forwarded-Proto':'https'}); "
                    "resp=urllib.request.urlopen(r,timeout=10); "
                    "assert resp.status==200, resp.status; print('READY_HTTP_200')"
                ),
            ],
            env=child_env,
        )
        evidence["status"] = "PASSED"

        procurement_args = [
            args.procurement_pack_output,
            args.procurement_performance_json,
            args.trial_run_record,
            args.remediation_register,
            args.training_record,
            args.external_integration_record,
        ]
        if any(procurement_args):
            if not all(procurement_args):
                raise AcceptanceGateError(
                    "final procurement package requires output + performance + trial-run + remediation + training + external-integration evidence"
                )
            # The strict package validator needs the successful runtime evidence.
            # Persist it before invoking the host-side builder; the finally block
            # will rewrite it once more with the procurement packaging phase.
            evidence["finishedAt"] = datetime.now(timezone.utc).isoformat()
            paths.evidence_file.write_text(
                json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            _phase(
                evidence,
                "procurement-evidence-package",
                [
                    sys.executable,
                    str(ROOT / "scripts" / "build_procurement_acceptance_package.py"),
                    "--runtime-evidence", str(paths.evidence_file),
                    "--initialization-snapshot", str(initialization_snapshot_host),
                    "--performance-evidence", args.procurement_performance_json,
                    "--trial-run-record", args.trial_run_record,
                    "--remediation-register", args.remediation_register,
                    "--training-record", args.training_record,
                    "--external-integration-record", args.external_integration_record,
                    "--output", args.procurement_pack_output,
                ],
                env=child_env,
            )
            evidence["procurementAcceptancePackage"] = str(Path(args.procurement_pack_output).resolve())

        print("HR_ACCEPTANCE_GATE_PASSED")
        return 0
    except (AcceptanceGateError, FileNotFoundError, subprocess.CalledProcessError) as exc:
        evidence["status"] = "FAILED"
        evidence["error"] = str(exc)
        print(f"HR_ACCEPTANCE_GATE_FAILED: {exc}", file=sys.stderr)
        return 1
    finally:
        evidence["finishedAt"] = datetime.now(timezone.utc).isoformat()
        paths.evidence_file.write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        if not args.keep:
            try:
                if not owns_project:
                    raise AcceptanceGateError("no owned namespace to clean up")
                subprocess.run(
                    [*compose, "down", "-v", "--remove-orphans"],
                    cwd=ROOT,
                    env=child_env,
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    text=True,
                )
            except Exception:
                pass
            try:
                paths.env_file.unlink(missing_ok=True)
            except Exception:
                pass
            shutil.rmtree(paths.root, ignore_errors=True)
        else:
            print(f"ACCEPTANCE_DEBUG_KEEP root={paths.root}")


if __name__ == "__main__":
    raise SystemExit(main())
