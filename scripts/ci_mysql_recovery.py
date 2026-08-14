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

from horilla_backup.mysqldump import dump_mysql_db


MARKER = "renshi-mysql-recovery-gate"
BACKUP_PATH = Path("/app/.ci-backup/horilla.sql")


def _mysql_command(database=None):
    db = settings.DATABASES["default"]
    command = [
        "mysql",
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
    dump_mysql_db(
        db_name=db["NAME"],
        username=db["USER"],
        output_file=BACKUP_PATH,
        password=db.get("PASSWORD"),
        host=db.get("HOST") or "localhost",
        port=db.get("PORT") or 3306,
    )
    if not BACKUP_PATH.exists() or BACKUP_PATH.stat().st_size == 0:
        raise RuntimeError("Backup artifact is empty")

    run_id = re.sub(r"[^0-9A-Za-z_]", "_", os.environ.get("GITHUB_RUN_ID", "local"))
    restore_database = f"horilla_restore_{run_id}"
    root_environment = _root_environment()

    subprocess.run(
        _mysql_command()
        + [
            "--execute",
            f"CREATE DATABASE `{restore_database}` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci",
        ],
        check=True,
        env=root_environment,
        text=True,
        capture_output=True,
    )

    with BACKUP_PATH.open("rb") as dump_file:
        subprocess.run(
            _mysql_command(restore_database),
            check=True,
            env=root_environment,
            stdin=dump_file,
            capture_output=True,
        )

    marker_result = subprocess.run(
        _mysql_command(restore_database)
        + [
            "--batch",
            "--skip-column-names",
            "--execute",
            "SELECT marker FROM backup_recovery_sentinel WHERE id = 1",
        ],
        check=True,
        env=root_environment,
        text=True,
        capture_output=True,
    ).stdout.strip()
    if marker_result != MARKER:
        raise RuntimeError(f"Restored sentinel mismatch: {marker_result!r}")

    migration_count = subprocess.run(
        _mysql_command(restore_database)
        + [
            "--batch",
            "--skip-column-names",
            "--execute",
            "SELECT COUNT(*) FROM django_migrations",
        ],
        check=True,
        env=root_environment,
        text=True,
        capture_output=True,
    ).stdout.strip()
    if int(migration_count) <= 0:
        raise RuntimeError("Restored database has no migration history")

    print(
        "MYSQL_RECOVERY_DRILL_OK",
        restore_database,
        f"migrations={migration_count}",
        f"backup_bytes={BACKUP_PATH.stat().st_size}",
    )


if __name__ == "__main__":
    main()
