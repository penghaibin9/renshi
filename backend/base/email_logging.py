"""Security helpers for tenant-scoped email audit logs."""

import logging
import re
from email.utils import parseaddr

import bleach
from django.db.models import Q

from horilla.horilla_middlewares import _thread_locals

logger = logging.getLogger(__name__)

_REDACTED_BODY = "<p>出于账户安全保护，认证类邮件正文不写入系统日志。</p>"
_SENSITIVE_MAIL_PATTERN = re.compile(
    r"(?:password\s*(?:reset|change)|reset\s*(?:your\s*)?password|"
    r"forgot\s*(?:your\s*)?password|one[-\s]?time\s*password|\botp\b|"
    r"verification\s*code|activation\s*(?:link|token)|"
    r"验证码|校验码|动态口令|一次性密码|重置密码|找回密码|账户激活|账号激活|"
    r"/reset/|/password-reset/|uidb64|token=)",
    re.IGNORECASE,
)

_ALLOWED_TAGS = {
    "a",
    "b",
    "blockquote",
    "br",
    "div",
    "em",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "hr",
    "i",
    "li",
    "ol",
    "p",
    "span",
    "strong",
    "table",
    "tbody",
    "td",
    "th",
    "thead",
    "tr",
    "u",
    "ul",
}
_ALLOWED_ATTRIBUTES = {"a": ["href", "title", "target"]}
_ALLOWED_PROTOCOLS = {"http", "https", "mailto"}


def sanitize_email_log_body(subject, body):
    """Return an audit-safe body and never persist authentication secrets."""

    subject = str(subject or "")
    body = str(body or "")
    if _SENSITIVE_MAIL_PATTERN.search(f"{subject}\n{body}"):
        return _REDACTED_BODY
    return bleach.clean(
        body,
        tags=_ALLOWED_TAGS,
        attributes=_ALLOWED_ATTRIBUTES,
        protocols=_ALLOWED_PROTOCOLS,
        strip=True,
        strip_comments=True,
    )


def resolve_email_log_company(request=None):
    """Resolve one concrete school for a mail log, or fail closed with ``None``."""

    request = request or getattr(_thread_locals, "request", None)
    if request is None:
        return None

    selected = getattr(request, "selected_company_instance", None)
    if getattr(selected, "pk", None):
        return selected

    company_id = getattr(request, "write_company_id", None)
    if company_id not in (None, "", "all"):
        return company_id

    session = getattr(request, "session", None)
    selected_id = session.get("selected_company") if session is not None else None
    if selected_id not in (None, "", "all"):
        return selected_id

    user = getattr(request, "user", None)
    if user and getattr(user, "is_authenticated", False):
        employee = getattr(user, "employee_get", None)
        if employee:
            return employee.get_company()
    return None


def email_log_recipient_q(*addresses):
    """Match normalized rows plus exact legacy list-string rows without substrings."""

    query = Q(pk__in=[])
    for raw_address in addresses:
        address = parseaddr(str(raw_address or ""))[1].strip().lower()
        if not address:
            continue
        query |= Q(to__iexact=address)
        query |= Q(to__iexact=str([address]))
        query |= Q(to__iexact=f'["{address}"]')
    return query


def record_email_log(*, subject, body, from_email, to, status, company=None):
    """Persist one sanitized, tenant-scoped audit row per primary recipient.

    Audit persistence must not turn a successfully delivered message into a retry,
    so logging failures are reported to the application logger and do not escape.
    """

    from base.models import EmailLog

    recipients = [to] if isinstance(to, str) else list(to or ())
    sender = parseaddr(str(from_email or ""))[1] or str(from_email or "")
    company = company or resolve_email_log_company()
    company_pk = getattr(company, "pk", company)
    safe_body = sanitize_email_log_body(subject, body)

    try:
        for raw_recipient in recipients:
            recipient = parseaddr(str(raw_recipient or ""))[1].strip().lower()
            if not recipient:
                continue
            EmailLog.objects.create(
                subject=str(subject or "")[:255],
                body=safe_body,
                from_email=sender,
                to=recipient,
                status=status,
                company_id_id=company_pk,
            )
    except Exception:
        logger.exception("Failed to persist sanitized email audit log")

