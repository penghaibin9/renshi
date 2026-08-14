"""Exact-head MySQL backup/restore acceptance drill used by Docker CI."""

import os
import re
import subprocess
from pathlib import Path

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "horilla.settings")

import django

django.setup()

from django.conf import settings
from django.db import connection

from horilla_backup.mysqldump import dump_mysql_db, resolve_mysql_client


MARKER = "renshi-mysql-recovery-gate"
BACKUP_PATH = Path("/app/.ci-backup/horilla.sql")


def _stage(name):
    print(f"MYSQL_RECOVERY_STAGE {name}", flush=True)


def _safe_detail(exc):
    detail = exc.stderr or exc.stdout or "command exited unsuccessfully"
    if isinstance(detail, bytes):
        detail = detail.decode("utf-8", errors="replace")
    return str(detail).strip()


def _run(stage, command, *, env, text=True, stdin=None):
    _stage(stage)
    try:
        return subprocess.run(
            command,
            check=True,
            env=env,
            text=text,
            stdin=stdin,
            capture_output=True,
        )
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            f"MYSQL_RECOVERY_FAILED stage={stage}: {_safe_detail(exc)}"
        ) from exc
    except OSError as exc:
        raise RuntimeError(f"MYSQL_RECOVERY_FAILED stage={stage}: {exc}") from exc


def _mysql_command(database=None):
    db = settings.DATABASES["default"]
    command = [
        resolve_mysql_client(),
        "--host",
        str(db.get("HOST") or "localhost"),
        "--port",
        str(db.get("PORT") or 3306),
        "--user",
        "root",
    ]
    if database:
        command.append(database)
    return command


def _root_environment():
    password = os.environ.get("MYSQL_CI_ROOT_PASSWORD")
    if not password:
        raise RuntimeError("MYSQL_CI_ROOT_PASSWORD is required for the recovery drill")
    environment = os.environ.copy()
    environment["MYSQL_PWD"] = password
    return environment


def main():
    if connection.vendor != "mysql":
        raise RuntimeError(f"Recovery drill requires MySQL, got {connection.vendor}")

    _stage("prepare-sentinel")
    with connection.cursor() as cursor:
        cursor.execute(
            "CREATE TABLE IF NOT EXISTS backup_recovery_sentinel ("
            "id INT PRIMARY KEY, marker VARCHAR(128) NOT NULL)"
        )
        cursor.execute("DELETE FROM backup_recovery_sentinel WHERE id = 1")
        cursor.execute(
            "INSERT INTO backup_recovery_sentinel (id, marker) VALUES (1, %s)",
            [MARKER],
        )

    db = settings.DATABASES["default"]
    _stage("backup")
    try:
        dump_mysql_db(
            db_name=db["NAME"],
            username=db["USER"],
            output_file=BACKUP_PATH,
            password=db.get("PASSWORD"),
            host=db.get("HOST") or "localhost",
            port=db.get("PORT") or 3306,
        )
    except Exception as exc:
        raise RuntimeError(f"MYSQL_RECOVERY_FAILED stage=backup: {exc}") from exc

    if not BACKUP_PATH.exists() or BACKUP_PATH.stat().st_size == 0:
        raise RuntimeError("MYSQL_RECOVERY_FAILED stage=backup: backup artifact is empty")

    run_id = re.sub(r"[^0-9A-Za-z_]", "_", os.environ.get("GITHUB_RUN_ID", "local"))
    restore_database = f"horilla_restore_{run_id}"
    root_environment = _root_environment()

    _run(
        "create-restore-db",
        _mysql_command()
        + [
            "--execute",
            f"CREATE DATABASE `{restore_database}` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci",
        ],
        env=root_environment,
    )

    with BACKUP_PATH.open("rb") as dump_file:
        _run(
            "restore",
            _mysql_command(restore_database),
            env=root_environment,
            text=False,
            stdin=dump_file,
        )

    marker_result = _run(
        "verify-sentinel",
        _mysql_command(restore_database)
        + [
            "--batch",
            "--skip-column-names",
            "--execute",
            "SELECT marker FROM backup_recovery_sentinel WHERE id = 1",
        ],
        env=root_environment,
    ).stdout.strip()
    if marker_result != MARKER:
        raise RuntimeError(
            f"MYSQL_RECOVERY_FAILED stage=verify-sentinel: "
            f"restored sentinel mismatch: {marker_result!r}"
        )

    migration_count = _run(
        "verify-migrations",
        _mysql_command(restore_database)
        + [
            "--batch",
            "--skip-column-names",
            "--execute",
            "SELECT COUNT(*) FROM django_migrations",
        ],
        env=root_environment,
    ).stdout.strip()
    if int(migration_count) <= 0:
        raise RuntimeError(
            "MYSQL_RECOVERY_FAILED stage=verify-migrations: "
            "restored database has no migration history"
        )

    print(
        "MYSQL_RECOVERY_DRILL_OK",
        restore_database,
        f"migrations={migration_count}",
        f"backup_bytes={BACKUP_PATH.stat().st_size}",
        flush=True,
    )


if __name__ == "__main__":
    main()
