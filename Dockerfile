# Build stage - compile Python/native dependencies for the MySQL-only stack.
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && apt-get install -y --no-install-recommends \
        build-essential \
        default-libmysqlclient-dev \
        libjpeg-dev \
        zlib1g-dev \
        libcairo2-dev \
        libpango1.0-dev \
        libgdk-pixbuf-xlib-2.0-dev \
        libxml2-dev \
        libxslt1-dev \
        libffi-dev \
        pkg-config \
        gcc \
        g++ \
    && rm -rf /var/lib/apt/lists/*

RUN rm -rf /opt/venv \
    && python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN /opt/venv/bin/python -m pip install --no-cache-dir --upgrade pip \
    && /opt/venv/bin/python -m pip install --no-cache-dir --upgrade --force-reinstall -r requirements.txt \
    && find /opt/venv -type d \( \
        -name 'msgpack-*.dist-info' -o \
        -name 'msgpack-*.egg-info' -o \
        -name 'setuptools-*.dist-info' -o \
        -name 'setuptools-*.egg-info' \
       \) -prune -exec rm -rf '{}' + \
    && /opt/venv/bin/python -m pip install --no-cache-dir --no-deps --force-reinstall \
        msgpack==1.2.1 \
        setuptools==83.0.0 \
    && /opt/venv/bin/python -m pip check \
    && /opt/venv/bin/python -c 'from importlib.metadata import distributions; from pathlib import Path; site_packages=next(Path("/opt/venv/lib").glob("python*/site-packages")); expected={"msgpack":"1.2.1","setuptools":"83.0.0"}; found={name:[d.version for d in distributions(path=[str(site_packages)]) if (d.metadata.get("Name") or "").lower()==name] for name in expected}; assert found=={name:[version] for name,version in expected.items()}, found' \
    && /opt/venv/bin/python -c 'from importlib.metadata import distribution; from pathlib import Path; root=Path("/opt/venv").resolve(); locations=[Path(distribution(name).locate_file("")).resolve() for name in ("msgpack", "setuptools")]; assert all(location == root or root in location.parents for location in locations), locations' \
    && /opt/venv/bin/python -c 'exec("""from pathlib import Path\nexpected = {\"msgpack\": \"1.2.1\", \"setuptools\": \"83.0.0\"}\nhits = []\nfor metadata in Path(\"/opt/venv\").rglob(\"*\"):\n    if not metadata.is_file() or metadata.name not in {\"METADATA\", \"PKG-INFO\"}:\n        continue\n    name = version = None\n    try:\n        for line in metadata.read_text(encoding=\"utf-8\", errors=\"replace\").splitlines():\n            if line.startswith(\"Name: \") and name is None:\n                name = line[6:].strip().lower()\n            elif line.startswith(\"Version: \") and version is None:\n                version = line[9:].strip()\n            if name is not None and version is not None:\n                break\n    except OSError:\n        continue\n    if name in expected and version != expected[name]:\n        hits.append((str(metadata), name, version, expected[name]))\nif hits:\n    print(\"Unsafe or stale Python package metadata detected in /opt/venv:\")\n    for path, name, version, wanted in hits:\n        print(f\"  {path}: {name} {version} (expected {wanted})\")\n    raise SystemExit(42)\n""")'

# Production stage - minimal runtime image.
FROM python:3.12-slim AS production

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && apt-get install -y --no-install-recommends \
        default-mysql-client \
        libmariadb3 \
        libjpeg62-turbo \
        zlib1g \
        libcairo2 \
        libpango-1.0-0 \
        libgdk-pixbuf-xlib-2.0-0 \
        libxml2 \
        libxslt1.1 \
        libffi8 \
        curl \
        netcat-openbsd \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

RUN useradd --create-home --uid 1000 appuser
COPY --from=builder --chown=appuser:appuser /opt/venv /opt/venv

WORKDIR /app
COPY --chown=appuser:appuser . .
COPY --chown=appuser:appuser docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

RUN mkdir -p staticfiles media \
    && chown -R appuser:appuser /app

USER appuser
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=30s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/health/ || exit 1

ENTRYPOINT ["/entrypoint.sh"]
CMD ["gunicorn", "horilla.wsgi:application", "--config", "docker/gunicorn.conf.py"]
