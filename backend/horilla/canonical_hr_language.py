"""Keep the canonical Yueke HR surface in Simplified Chinese.

The upstream Horilla repository supports many languages.  Canonical HR01-HR18
pages intentionally use one Chinese product surface so an old language cookie
cannot drop users back into a mixed English/Chinese experience.
"""
from __future__ import annotations

from django.conf import settings
from django.utils import translation


class CanonicalHrLanguageMiddleware:
    """Force only canonical HR/public-recruitment UI requests to zh-hans."""

    def __init__(self, get_response):
        self.get_response = get_response

    @staticmethod
    def _is_canonical_ui(path: str) -> bool:
        return (
            path == "/login/"
            or path.startswith("/hr/")
            or path.startswith("/recruit/")
            or path.startswith("/settings/")
        )

    def __call__(self, request):
        force = self._is_canonical_ui(request.path_info or "")
        if force:
            language = getattr(settings, "HR_CANONICAL_LANGUAGE", "zh-hans")
            translation.activate(language)
            request.LANGUAGE_CODE = language
        response = self.get_response(request)
        if force:
            response["Content-Language"] = getattr(settings, "HR_CANONICAL_LANGUAGE", "zh-hans")
        return response
