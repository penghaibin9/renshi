"""Deferred initialization for database-configured, Web-only automations."""

import logging


logger = logging.getLogger(__name__)
_SKIP_PREFIXES = ("/health/", "/ready/", "/login", "/static/", "/media/")


class RuntimeAutomationMiddleware:
    """Initialize optional dynamic signals without coupling liveness to MySQL."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.path_info.startswith(_SKIP_PREFIXES):
            self._initialize_optional_automations()
        return self.get_response(request)

    @staticmethod
    def _initialize_optional_automations():
        from horilla_automations.apps import initialize_mail_automation_once
        from horilla_audit.registry import apply_database_configuration_if_changed
        from pms.apps import initialize_pms_automation_once

        for name, initializer in (
            ("audit", apply_database_configuration_if_changed),
            ("mail", initialize_mail_automation_once),
            ("pms", initialize_pms_automation_once),
        ):
            try:
                initializer()
            except Exception:
                # These are optional legacy-compatible event automations. A
                # transient rule-query failure must not take the whole HR UI
                # down; the uninitialized flag makes the next request retry.
                logger.exception("deferred %s automation initialization failed", name)
