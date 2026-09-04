"""Safe, in-process HTML to PDF rendering helpers."""

from __future__ import annotations

import re
from io import BytesIO
from pathlib import Path
from urllib.parse import unquote, urlsplit

from django.conf import settings
from django.contrib.staticfiles import finders
from xhtml2pdf import pisa

MAX_HTML_BYTES = 5 * 1024 * 1024
MAX_INLINE_IMAGE_BYTES = 5 * 1024 * 1024
_SAFE_INLINE_IMAGE_PREFIXES = (
    "data:image/png;base64,",
    "data:image/jpeg;base64,",
    "data:image/gif;base64,",
    "data:image/webp;base64,",
)
_CJK_PATTERN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_CJK_STYLE = "<style>body, body * { font-family: STSong-Light; }</style>"


class PDFRenderError(RuntimeError):
    """Raised when an HTML document cannot be rendered as a PDF."""


def _safe_child(root: str | Path, relative_path: str) -> str:
    """Resolve *relative_path* below *root* and reject path traversal."""

    root_path = Path(root).resolve()
    candidate = (root_path / relative_path.lstrip("/\\")).resolve()
    try:
        candidate.relative_to(root_path)
    except ValueError as exc:
        raise PDFRenderError("PDF resource path escapes its configured root") from exc
    if not candidate.is_file():
        raise PDFRenderError("PDF resource was not found")
    return str(candidate)


def _url_path_prefix(value: str | None) -> str:
    path = urlsplit(value or "").path
    return path if path.endswith("/") else f"{path}/"


def safe_resource_path(uri: str, _relative_uri: str | None = None) -> str:
    """Resolve only local static/media assets for xhtml2pdf.

    Remote URLs and ``file://`` paths are deliberately rejected. Absolute
    same-site media URLs are mapped by URL path and never fetched over HTTP.
    """

    if not isinstance(uri, str) or not uri.strip():
        raise PDFRenderError("PDF resource URI is empty")

    value = uri.strip()
    if value.lower().startswith(_SAFE_INLINE_IMAGE_PREFIXES):
        if len(value.encode("ascii", errors="ignore")) > MAX_INLINE_IMAGE_BYTES:
            raise PDFRenderError("Inline PDF image is too large")
        return value

    parsed = urlsplit(value)
    if parsed.scheme and parsed.scheme not in {"http", "https"}:
        raise PDFRenderError("PDF resource URI scheme is not allowed")

    path = unquote(parsed.path).replace("\\", "/")
    static_prefix = _url_path_prefix(getattr(settings, "STATIC_URL", "/static/"))
    media_prefix = _url_path_prefix(getattr(settings, "MEDIA_URL", "/media/"))

    if path.startswith(static_prefix):
        relative = path[len(static_prefix) :]
        found = finders.find(relative)
        if isinstance(found, (list, tuple)):
            found = found[0] if found else None
        if not found or not Path(found).is_file():
            raise PDFRenderError("PDF static resource was not found")
        return str(Path(found).resolve())

    if path.startswith(media_prefix):
        return _safe_child(settings.MEDIA_ROOT, path[len(media_prefix) :])

    # Relative asset references are resolved only through Django staticfiles.
    if not parsed.scheme and not parsed.netloc and not path.startswith("/"):
        found = finders.find(path)
        if isinstance(found, (list, tuple)):
            found = found[0] if found else None
        if found and Path(found).is_file():
            return str(Path(found).resolve())

    raise PDFRenderError("Remote and arbitrary local PDF resources are not allowed")


def render_html_to_pdf(html: str) -> bytes:
    """Render HTML without a browser, JavaScript, cookies, or network access."""

    if not isinstance(html, str):
        raise TypeError("html must be a string")
    if len(html.encode("utf-8")) > MAX_HTML_BYTES:
        raise PDFRenderError("HTML document is too large")

    if _CJK_PATTERN.search(html):
        closing_head = re.search(r"</head\s*>", html, flags=re.IGNORECASE)
        if closing_head:
            html = (
                html[: closing_head.start()]
                + _CJK_STYLE
                + html[closing_head.start() :]
            )
        else:
            html = f"{_CJK_STYLE}{html}"

    output = BytesIO()
    status = pisa.CreatePDF(
        src=html,
        dest=output,
        encoding="utf-8",
        link_callback=safe_resource_path,
    )
    if status.err:
        raise PDFRenderError("PDF rendering failed")
    return output.getvalue()
