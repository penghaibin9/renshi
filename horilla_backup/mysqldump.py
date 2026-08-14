import os
import subprocess
import tempfile
from pathlib import Path


class MySQLBackupError(RuntimeError):
    """Raised when a MySQL backup cannot be produced safely."""


def dump_mysql_db(
    db_name,
    username,
    output_file,
    password=None,
    host="localhost",
    port=3306,
):
    """Create an atomic logical MySQL backup with mysqldump.

    The password is passed only through the child process environment and is
    never exposed in the process argument list.  A failed dump never replaces
    an existing known-good backup.
    """

    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output_path.name}.",
        suffix=".tmp",
        dir=output_path.parent,
    )
    os.close(descriptor)
    temporary_path = Path(temporary_name)

    command = [
        "mysqldump",
        "--host",
        str(host or "localhost"),
        "--port",
        str(port or 3306),
        "--user",
        str(username),
        "--single-transaction",
        "--quick",
        "--routines",
        "--triggers",
        "--hex-blob",
        "--no-tablespaces",
        "--default-character-set=utf8mb4",
        f"--result-file={temporary_path}",
        str(db_name),
    ]

    child_environment = os.environ.copy()
    if password:
        child_environment["MYSQL_PWD"] = str(password)

    try:
        subprocess.run(
            command,
            check=True,
            text=True,
            capture_output=True,
            env=child_environment,
        )
        if not temporary_path.exists() or temporary_path.stat().st_size == 0:
            raise MySQLBackupError("mysqldump completed without producing backup data")
        os.replace(temporary_path, output_path)
    except subprocess.CalledProcessError as exc:
        temporary_path.unlink(missing_ok=True)
        detail = (exc.stderr or exc.stdout or "mysqldump exited unsuccessfully").strip()
        raise MySQLBackupError(f"MySQL backup failed: {detail}") from exc
    except (OSError, MySQLBackupError) as exc:
        temporary_path.unlink(missing_ok=True)
        if isinstance(exc, MySQLBackupError):
            raise
        raise MySQLBackupError(f"MySQL backup failed: {exc}") from exc
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise

    return output_path
