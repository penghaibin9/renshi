"""Central malware scanning for every multipart upload.

The client implements ClamAV's small ``INSTREAM`` protocol directly so the
security boundary does not depend on a Python wrapper that can lag behind the
daemon.  Production is configured to fail closed; local development can leave
the feature disabled explicitly.
"""

from __future__ import annotations

import logging
import socket
import struct
from contextlib import closing

from django.conf import settings
from django.http import JsonResponse
from django.utils.deprecation import MiddlewareMixin

logger = logging.getLogger(__name__)


class MalwareScanError(Exception):
    """A stable, non-sensitive malware scan failure."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def _receive_response(sock, *, limit: int = 4096) -> str:
    response = bytearray()
    while len(response) < limit:
        chunk = sock.recv(min(1024, limit - len(response)))
        if not chunk:
            break
        response.extend(chunk)
        if b"\0" in chunk or b"\n" in chunk:
            break
    if not response:
        raise MalwareScanError("scanner_protocol_error", "empty scanner response")
    return bytes(response).rstrip(b"\0\r\n").decode("utf-8", errors="replace")


def _connect():
    host = str(getattr(settings, "MALWARE_SCAN_HOST", "") or "").strip()
    port = int(getattr(settings, "MALWARE_SCAN_PORT", 3310))
    timeout = float(getattr(settings, "MALWARE_SCAN_TIMEOUT_SECONDS", 10))
    if not host:
        raise MalwareScanError("scanner_unavailable", "scanner host is not configured")
    try:
        return socket.create_connection((host, port), timeout=timeout)
    except (OSError, ValueError) as exc:
        raise MalwareScanError("scanner_unavailable", "scanner connection failed") from exc


def ping_malware_scanner() -> None:
    """Raise ``MalwareScanError`` unless clamd answers its private TCP probe."""

    try:
        with closing(_connect()) as sock:
            sock.sendall(b"zPING\0")
            response = _receive_response(sock)
    except MalwareScanError:
        raise
    except OSError as exc:
        raise MalwareScanError("scanner_unavailable", "scanner ping failed") from exc
    if response != "PONG":
        raise MalwareScanError("scanner_protocol_error", "unexpected scanner response")


def scan_uploaded_file(uploaded_file) -> None:
    """Stream one Django UploadedFile to clamd and restore its read position."""

    max_bytes = int(getattr(settings, "MALWARE_SCAN_MAX_BYTES", 50 * 1024 * 1024))
    declared_size = getattr(uploaded_file, "size", None)
    if declared_size is not None and int(declared_size) > max_bytes:
        raise MalwareScanError("file_too_large", "file exceeds malware scan limit")

    try:
        original_position = uploaded_file.tell()
    except (AttributeError, OSError):
        original_position = 0

    total = 0
    try:
        uploaded_file.seek(0)
        try:
            with closing(_connect()) as sock:
                sock.sendall(b"zINSTREAM\0")
                for chunk in uploaded_file.chunks(chunk_size=64 * 1024):
                    total += len(chunk)
                    if total > max_bytes:
                        raise MalwareScanError(
                            "file_too_large", "file exceeds malware scan limit"
                        )
                    sock.sendall(struct.pack(">I", len(chunk)))
                    sock.sendall(chunk)
                sock.sendall(struct.pack(">I", 0))
                response = _receive_response(sock)
        except MalwareScanError:
            raise
        except OSError as exc:
            raise MalwareScanError(
                "scanner_unavailable", "scanner stream failed"
            ) from exc

        if response.endswith(" OK"):
            return
        if response.endswith(" FOUND"):
            raise MalwareScanError("malware_detected", "malware signature detected")
        raise MalwareScanError(
            "scanner_protocol_error", "scanner did not return a clean verdict"
        )
    finally:
        try:
            uploaded_file.seek(original_position)
        except (AttributeError, OSError):
            try:
                uploaded_file.seek(0)
            except (AttributeError, OSError):
                pass


class MalwareScanMiddleware(MiddlewareMixin):
    """Fail closed after CSRF/auth checks and before the business view."""

    _upload_methods = frozenset({"POST", "PUT", "PATCH"})

    def process_view(self, request, view_func, view_args, view_kwargs):
        if not getattr(settings, "MALWARE_SCAN_REQUIRED", False):
            return None
        if request.method not in self._upload_methods:
            return None

        for _, uploaded_files in request.FILES.lists():
            for uploaded_file in uploaded_files:
                if getattr(uploaded_file, "_malware_scan_complete", False):
                    continue
                try:
                    scan_uploaded_file(uploaded_file)
                except MalwareScanError as exc:
                    status = 422 if exc.code == "malware_detected" else 503
                    if exc.code == "file_too_large":
                        status = 413
                    logger.warning(
                        "upload rejected by malware security gate code=%s",
                        exc.code,
                    )
                    response = JsonResponse(
                        {"detail": "上传文件未通过安全检查。", "code": exc.code},
                        status=status,
                    )
                    response["Cache-Control"] = "no-store"
                    return response
                uploaded_file._malware_scan_complete = True

        return None
