# Gunicorn configuration for the university HR platform
# This file provides advanced configuration options for the WSGI server

import multiprocessing
import os

# Bind settings
bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"
host = "0.0.0.0"
port = int(os.environ.get("PORT", "8000"))

# Worker settings. Treat an explicitly empty environment value as "automatic"
# so a templating mistake cannot crash Gunicorn with ``int("")``.
_configured_workers = os.environ.get("GUNICORN_WORKERS", "").strip()
workers = (
    int(_configured_workers)
    if _configured_workers
    else max(2, min(multiprocessing.cpu_count() * 2 + 1, 8))
)
if not 1 <= workers <= 32:
    raise ValueError("GUNICORN_WORKERS must be between 1 and 32")
worker_class = "gthread"
threads = 4
worker_connections = 1000
max_requests = 1000
max_requests_jitter = 50
# Production preloads Django once in the master, then forks workers. Startup is
# intentionally database-free, and post_fork closes any accidental inherited
# connections, so this avoids repeating the large HR URL/model import graph in
# every worker without sharing live ORM connections.
preload_app = os.environ.get("GUNICORN_PRELOAD", "false").lower() in {
    "1",
    "true",
    "yes",
}

# Timeout settings
timeout = 120
graceful_timeout = 60
keepalive = 5

# Logging
accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("GUNICORN_LOG_LEVEL", "info")
# Never log query strings or Referer values. HR download tickets and other
# one-time credentials can appear in URLs; Referer can carry the previous URL
# (including its query) even when the current request path is clean.
# Gunicorn atoms: m=method, U=URL path without query, H=protocol.
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(m)s %(U)s %(H)s" %(s)s %(b)s "%(a)s" %(D)s'

# Process naming
proc_name = "university-hr-platform"

# Server mechanics
pidfile = "/tmp/gunicorn.pid"
# Gunicorn 25+ enables a Unix control socket under $HOME by default. The
# production container intentionally has a read-only root filesystem and does
# not use this administrative socket, so disable it instead of weakening the
# filesystem boundary or emitting a misleading startup ERROR.
control_socket_disable = True
user = None  # Run as current user in container
group = None
tmp_upload_dir = None

# Development settings
reload = os.environ.get("GUNICORN_RELOAD", "false").lower() == "true"


def post_fork(server, worker):
    from django.conf import settings as django_settings
    from django.db import connections

    if django_settings.configured:
        connections.close_all()

# SSL settings (if needed)
# ssl_keyfile = os.environ.get('SSL_KEYFILE')
# ssl_certfile = os.environ.get('SSL_CERTFILE')
