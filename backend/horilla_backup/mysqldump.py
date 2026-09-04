import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path


class MySQLBackupError(RuntimeError):
    """Raised when a MySQL backup cannot be produced safely."""


_INSERT_RE = re.compile(
    r"^INSERT INTO `(?P<table>[^`]+)` \((?P<columns>.+)\) VALUES \((?P<values>.*)\);$"
)


def _resolve_client(*names):
    for name in names:
        executable = shutil.which(name)
        if executable:
            return executable
    raise MySQLBackupError(
        "MySQL client is unavailable; expected one of: " + ", ".join(names)
    )


def resolve_mysql_client():
    """Return the installed MySQL-compatible interactive client."""

    return _resolve_client("mysql", "mariadb")


def resolve_mysql_dump_client():
    """Return the installed MySQL-compatible logical dump client."""

    return _resolve_client("mysqldump", "mariadb-dump")


def _child_environment(password):
    environment = os.environ.copy()
    if password:
        environment["MYSQL_PWD"] = str(password)
    return environment


def _safe_detail(exc, fallback):
    detail = exc.stderr or exc.stdout or fallback
    if isinstance(detail, bytes):
        detail = detail.decode("utf-8", errors="replace")
    return str(detail).strip()


def _schema_object_count(
    object_table,
    db_name,
    username,
    password,
    host,
    port,
):
    """Count schema-owned stored objects using the same least-privilege account.

    MySQL 8.4 requires extra global visibility to dump stored routines with
    ``--routines``. A normal application account should not need that global
    privilege when the schema has no routines. We therefore detect whether
    routines/events actually exist and request their dump only when needed;
    if they do exist and the backup account cannot dump them, the dump fails
    closed rather than silently producing an incomplete backup.
    """

    if object_table not in {"ROUTINES", "EVENTS"}:
        raise ValueError(f"Unsupported schema object table: {object_table}")

    client = resolve_mysql_client()
    command = [
        client,
        "--host",
        str(host or "localhost"),
        "--port",
        str(port or 3306),
        "--user",
        str(username),
        f"--database={db_name}",
        "--batch",
        "--skip-column-names",
        "--execute",
        (
            f"SELECT COUNT(*) FROM information_schema.{object_table} "
            "WHERE "
            + ("ROUTINE_SCHEMA" if object_table == "ROUTINES" else "EVENT_SCHEMA")
            + " = DATABASE()"
        ),
    ]
    environment = _child_environment(password)
    try:
        result = subprocess.run(
            command,
            check=True,
            text=True,
            capture_output=True,
            env=environment,
        )
    except subprocess.CalledProcessError as exc:
        detail = _safe_detail(exc, "schema-object preflight exited unsuccessfully")
        raise MySQLBackupError(
            f"MySQL backup preflight for {object_table.lower()} failed: {detail}"
        ) from exc
    except OSError as exc:
        raise MySQLBackupError(
            f"MySQL backup preflight for {object_table.lower()} failed: {exc}"
        ) from exc

    raw_count = result.stdout.strip()
    try:
        return int(raw_count)
    except ValueError as exc:
        raise MySQLBackupError(
            f"MySQL backup preflight returned invalid {object_table.lower()} count: "
            f"{raw_count!r}"
        ) from exc


def _generated_columns(db_name, username, password, host, port):
    client = resolve_mysql_client()
    command = [
        client,
        "--host",
        str(host or "localhost"),
        "--port",
        str(port or 3306),
        "--user",
        str(username),
        f"--database={db_name}",
        "--batch",
        "--skip-column-names",
        "--execute",
        (
            "SELECT TABLE_NAME, COLUMN_NAME FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() AND EXTRA LIKE '%GENERATED%' "
            "ORDER BY TABLE_NAME, ORDINAL_POSITION"
        ),
    ]
    try:
        result = subprocess.run(
            command,
            check=True,
            text=True,
            capture_output=True,
            env=_child_environment(password),
        )
    except (subprocess.CalledProcessError, OSError) as exc:
        detail = _safe_detail(exc, "generated-column preflight failed")
        raise MySQLBackupError(
            f"MySQL generated-column preflight failed: {detail}"
        ) from exc
    generated = {}
    for line in result.stdout.splitlines():
        try:
            table, column = line.split("\t", 1)
        except ValueError as exc:
            raise MySQLBackupError(
                f"Invalid generated-column metadata row: {line!r}"
            ) from exc
        generated.setdefault(table, set()).add(column)
    return generated


def _split_sql_values(values):
    """Split one mysqldump VALUES tuple without breaking quoted commas."""
    result = []
    start = 0
    quoted = False
    escaped = False
    for index, character in enumerate(values):
        if escaped:
            escaped = False
            continue
        if quoted and character == "\\":
            escaped = True
            continue
        if character == "'":
            quoted = not quoted
        elif character == "," and not quoted:
            result.append(values[start:index])
            start = index + 1
    if quoted:
        raise MySQLBackupError("Unterminated SQL string in dump INSERT")
    result.append(values[start:])
    return result


def rewrite_generated_column_inserts(dump_path, generated_columns):
    """Replace dumped generated values with DEFAULT for MySQL 8 restores.

    Debian's MariaDB-compatible dump client includes generated columns in data
    INSERTs when connected to MySQL 8. MySQL correctly rejects explicit values
    for those columns. ``DEFAULT`` is the only portable allowed value and asks
    the target server to recompute the generated expression.
    """
    dump_path = Path(dump_path)
    if not generated_columns:
        return 0
    descriptor, rewritten_name = tempfile.mkstemp(
        prefix=f".{dump_path.name}.generated.",
        suffix=".tmp",
        dir=dump_path.parent,
    )
    os.close(descriptor)
    rewritten_path = Path(rewritten_name)
    replacements = 0
    try:
        with dump_path.open("r", encoding="utf-8", newline="") as source, rewritten_path.open(
            "w", encoding="utf-8", newline=""
        ) as target:
            for line in source:
                stripped = line.rstrip("\r\n")
                match = _INSERT_RE.match(stripped)
                generated = generated_columns.get(match.group("table")) if match else None
                if not generated:
                    target.write(line)
                    continue
                columns = [
                    item.strip().removeprefix("`").removesuffix("`")
                    for item in match.group("columns").split(",")
                ]
                values = _split_sql_values(match.group("values"))
                if len(columns) != len(values):
                    raise MySQLBackupError(
                        f"Column/value mismatch while rewriting {match.group('table')}"
                    )
                for index, column in enumerate(columns):
                    if column in generated:
                        values[index] = "DEFAULT"
                        replacements += 1
                newline = "\r\n" if line.endswith("\r\n") else "\n"
                target.write(
                    f"INSERT INTO `{match.group('table')}` ({match.group('columns')}) "
                    f"VALUES ({','.join(values)});{newline}"
                )
        os.replace(rewritten_path, dump_path)
    except Exception:
        rewritten_path.unlink(missing_ok=True)
        raise
    return replacements


def dump_mysql_db(
    db_name,
    username,
    output_file,
    password=None,
    host="localhost",
    port=3306,
):
    """Create an atomic, restorable logical MySQL backup.

    Passwords are passed only through the child-process environment and never
    exposed in argv. Stored routines/events are included when they actually
    exist; if required privileges are insufficient, backup generation fails
    closed. A failed dump never replaces an existing known-good backup.
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

    dump_client = resolve_mysql_dump_client()
    routine_count = _schema_object_count(
        "ROUTINES", db_name, username, password, host, port
    )
    event_count = _schema_object_count(
        "EVENTS", db_name, username, password, host, port
    )
    generated_columns = _generated_columns(
        db_name, username, password, host, port
    )

    command = [
        dump_client,
        "--host",
        str(host or "localhost"),
        "--port",
        str(port or 3306),
        "--user",
        str(username),
        "--single-transaction",
        "--quick",
        "--triggers",
        "--hex-blob",
        "--complete-insert",
        "--skip-extended-insert",
        "--no-tablespaces",
        "--default-character-set=utf8mb4",
        f"--result-file={temporary_path}",
    ]
    if routine_count:
        command.append("--routines")
    if event_count:
        command.append("--events")
    command.append(str(db_name))

    child_environment = _child_environment(password)

    try:
        subprocess.run(
            command,
            check=True,
            text=True,
            capture_output=True,
            env=child_environment,
        )
        if not temporary_path.exists() or temporary_path.stat().st_size == 0:
            raise MySQLBackupError(
                f"{Path(dump_client).name} completed without producing backup data"
            )
        rewrite_generated_column_inserts(temporary_path, generated_columns)
        os.replace(temporary_path, output_path)
    except subprocess.CalledProcessError as exc:
        temporary_path.unlink(missing_ok=True)
        detail = _safe_detail(exc, f"{Path(dump_client).name} exited unsuccessfully")
        object_hint = ""
        if routine_count:
            object_hint += " routines-present"
        if event_count:
            object_hint += " events-present"
        raise MySQLBackupError(
            f"MySQL backup failed via {Path(dump_client).name}:{object_hint} {detail}"
        ) from exc
    except (OSError, MySQLBackupError) as exc:
        temporary_path.unlink(missing_ok=True)
        if isinstance(exc, MySQLBackupError):
            raise
        raise MySQLBackupError(f"MySQL backup failed: {exc}") from exc
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise

    return output_path
