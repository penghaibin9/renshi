"""Template filters for rendering historical mail logs safely."""

from django import template

from base.email_logging import sanitize_email_log_body

register = template.Library()


@register.filter
def safe_email_log_body(email_log):
    """Sanitize both legacy and newly written log bodies at the display boundary."""

    if email_log is None:
        return ""
    return sanitize_email_log_body(email_log.subject, email_log.body)

