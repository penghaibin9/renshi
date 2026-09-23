#!/usr/bin/env python3
"""Fail fast when the host cannot safely parse the production Compose overlay."""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys

MIN_COMPOSE = (2, 24, 4)  # docker-compose.prod.yml uses !override


def _run(command):
    return subprocess.run(command, check=True, text=True, capture_output=True)


def _version_tuple(raw):
    match = re.search(r"(?<!\d)(\d+)\.(\d+)\.(\d+)(?!\d)", raw)
    if not match:
        raise ValueError(raw.strip())
    return tuple(int(part) for part in match.groups())


def main():
    compose = shlex.split(os.environ.get("COMPOSE_COMMAND", "docker compose"))
    if not compose:
        print("PROD_COMPOSE_PREFLIGHT_FAILED: empty COMPOSE_COMMAND", file=sys.stderr)
        return 2
    try:
        version_result = _run([*compose, "version", "--short"])
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        print(
            "PROD_COMPOSE_PREFLIGHT_FAILED: Docker Compose is unavailable or failed to run",
            file=sys.stderr,
        )
        if isinstance(exc, subprocess.CalledProcessError) and exc.stderr:
            print(exc.stderr.strip(), file=sys.stderr)
        return 2

    raw_version = version_result.stdout or version_result.stderr
    try:
        version = _version_tuple(raw_version)
    except ValueError:
        print(
            f"PROD_COMPOSE_PREFLIGHT_FAILED: cannot parse Compose version: {raw_version.strip()}",
            file=sys.stderr,
        )
        return 2

    if version < MIN_COMPOSE:
        required = ".".join(map(str, MIN_COMPOSE))
        current = ".".join(map(str, version))
        print(
            f"PROD_COMPOSE_PREFLIGHT_FAILED: Docker Compose {current} is too old; "
            f">={required} is required because the production overlay uses !override.",
            file=sys.stderr,
        )
        return 2

    config_command = [
        *compose,
        "-f",
        "docker-compose.yml",
        "-f",
        "docker-compose.prod.yml",
        "config",
        "--quiet",
    ]
    try:
        _run(config_command)
    except subprocess.CalledProcessError as exc:
        print("PROD_COMPOSE_PREFLIGHT_FAILED: production Compose config is invalid", file=sys.stderr)
        if exc.stderr:
            print(exc.stderr.strip(), file=sys.stderr)
        return exc.returncode or 2

    print(
        "PROD_COMPOSE_PREFLIGHT_OK "
        f"compose={'.'.join(map(str, version))} min={'.'.join(map(str, MIN_COMPOSE))}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
