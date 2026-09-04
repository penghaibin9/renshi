"""
hr_recruitment/public/views.py

招聘公开门户 API（S5）。

A0 硬门：
- 公开入口由 campaign public_token 解析学校，禁止客户端传 tenant_id。
- public endpoint 不得枚举 ID 访问其他学校招聘。
- 候选人只能看到本人数据。
- public 候选账号与员工/HR 账号隔离（无需登录，用身份因子绑定本人申请）。

端点：
  GET  /recruit/{token}                           公开岗位列表
  GET  /recruit/{token}/positions/{position_slug} 岗位详情
  POST /recruit/{token}/apply                     提交申请（幂等，Idempotency-Key）
  GET  /recruit/my-applications                   按 email+mobile 查本人申请
"""

from __future__ import annotations

import json
import logging
import secrets
import time
from datetime import timedelta

from django.apps import apps
from django.conf import settings
from django.core import signing
from django.core.cache import cache
from django.utils.crypto import constant_time_compare, salted_hmac
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from hr_recruitment.api.base import (
    error,
    get_idempotency_key,
    ok,
)
from hr_recruitment.api.exceptions import Hr04ApiError
from hr_recruitment.constants import (
    ApplicationCanonicalStatus,
    CampaignStatus,
    CandidateStatus,
)
from hr_recruitment.labels import APPLICATION_STATUS_LABELS, status_label
from hr_recruitment.models import HrJobApplication, HrRecruitmentCampaign, HrRecruitmentPosition
from hr_recruitment.services.application_service import ApplicationService, ApplicationServiceError
from hr_recruitment.services.candidate_service import CandidateService, CandidateServiceError


PUBLIC_RECEIPT_SALT = "hr04.public.candidate-receipt.v1"
PUBLIC_JSON_MAX_BYTES = 64 * 1024
PUBLIC_RATE_WINDOW_SECONDS = 60 * 60
PUBLIC_APPLY_IDENTITY_LIMIT = 10
PUBLIC_RECEIPT_QUERY_LIMIT = 120
PUBLIC_RECEIPT_RECOVERY_LIMIT = 5
PUBLIC_SHARED_IP_LIMIT = 1000
PUBLIC_RECEIPT_OTP_TTL_SECONDS = 300
PUBLIC_RECEIPT_OTP_MAX_ATTEMPTS = 5
logger = logging.getLogger(__name__)


def send_deployment_email(*args, **kwargs):
    """Load the legacy mail adapter only when recovery mail is actually sent."""
    from base.backends import send_deployment_email as legacy_sender

    return legacy_sender(*args, **kwargs)


class PublicPortalError(Exception):
    def __init__(self, code, message, status):
        self.code = code
        self.message = message
        self.status = status
        super().__init__(message)


def _json_object(request):
    if request.content_type != "application/json":
        raise PublicPortalError(
            "JSON_CONTENT_TYPE_REQUIRED",
            "请求必须使用 application/json",
            415,
        )
    try:
        declared_size = int(request.META.get("CONTENT_LENGTH") or 0)
    except (TypeError, ValueError):
        declared_size = 0
    if declared_size > PUBLIC_JSON_MAX_BYTES:
        raise PublicPortalError("REQUEST_TOO_LARGE", "请求内容不能超过 64KB", 413)
    raw_body = request.body
    if len(raw_body) > PUBLIC_JSON_MAX_BYTES:
        raise PublicPortalError("REQUEST_TOO_LARGE", "请求内容不能超过 64KB", 413)
    body = json.loads(raw_body or b"{}")
    if not isinstance(body, dict):
        raise ValueError("request body must be a JSON object")
    return body


def _client_ip(request):
    if getattr(settings, "FAIL2BAN_TRUST_X_REAL_IP", False):
        forwarded = str(request.META.get("HTTP_X_REAL_IP", "")).strip()
        if forwarded:
            return forwarded
    return str(request.META.get("REMOTE_ADDR", "unknown")).strip() or "unknown"


def _rate_digest(value):
    return salted_hmac("hr04.public.rate.v1", str(value)).hexdigest()


def _rate_count(key):
    try:
        if cache.add(key, 1, timeout=PUBLIC_RATE_WINDOW_SECONDS):
            return 1
        return cache.incr(key)
    except Exception:  # cache failure must not silently lose a real application
        logger.exception("HR04 public rate-limit cache unavailable")
        return 0


def _rate_limited(
    request, *, scope, identity="", identity_limit=0, include_ip=True
):
    if include_ip:
        ip_key = f"hr04-public-rate:{scope}:ip:{_rate_digest(_client_ip(request))}"
        if _rate_count(ip_key) > PUBLIC_SHARED_IP_LIMIT:
            return True
    if identity and identity_limit:
        identity_key = f"hr04-public-rate:{scope}:identity:{_rate_digest(identity)}"
        if _rate_count(identity_key) > identity_limit:
            return True
    return False


def _rate_limit_response(request):
    return error(
        request,
        "PUBLIC_RATE_LIMITED",
        "请求过于频繁，请稍后再试",
        429,
    )


def _challenge_cache_key(challenge_id):
    return f"hr04-public-receipt-challenge:{_rate_digest(challenge_id)}"


def _challenge_otp_hash(challenge_id, otp):
    return salted_hmac(
        "hr04.public.receipt-recovery-otp.v1",
        f"{challenge_id}:{otp}",
    ).hexdigest()


def _issue_receipt_recovery_challenge(request, campaign, *, email, mobile):
    from hr_recruitment.models import HrRecruitmentCandidate

    email = str(email or "").strip().lower()
    mobile = str(mobile or "").strip()
    if not email or not mobile:
        raise PublicPortalError("INSUFFICIENT_IDENTITY", "邮箱和手机号均为必填项", 422)
    if _rate_limited(
        request,
        scope="receipt-recovery",
        identity=f"{campaign.tenant_id}|{email}|{mobile}",
        identity_limit=PUBLIC_RECEIPT_RECOVERY_LIMIT,
        include_ip=False,
    ):
        raise PublicPortalError("PUBLIC_RATE_LIMITED", "请求过于频繁，请稍后再试", 429)

    candidate = HrRecruitmentCandidate.objects.filter(
        tenant_id=campaign.tenant_id,
        status=CandidateStatus.ACTIVE,
        primary_email__iexact=email,
        primary_mobile=mobile,
    ).first()
    challenge_id = secrets.token_urlsafe(24)
    otp = f"{secrets.randbelow(1_000_000):06d}"
    payload = {
        "tenant_id": int(campaign.tenant_id),
        "candidate_uid": candidate.candidate_uid if candidate else "",
        "otp_hash": _challenge_otp_hash(challenge_id, otp),
        "attempts": 0,
        "expires_at": time.time() + PUBLIC_RECEIPT_OTP_TTL_SECONDS,
    }
    try:
        cache.set(
            _challenge_cache_key(challenge_id),
            payload,
            timeout=PUBLIC_RECEIPT_OTP_TTL_SECONDS,
        )
    except Exception as exc:
        logger.exception("HR04 receipt recovery cache unavailable")
        raise PublicPortalError(
            "RECEIPT_RECOVERY_UNAVAILABLE", "查询凭证找回服务暂时不可用", 503
        ) from exc

    if candidate:
        try:
            accepted = send_deployment_email(
                subject="高校招聘报名查询验证码",
                body=(
                    f"您正在找回“{campaign.title}”的报名查询凭证。\n\n"
                    f"验证码：{otp}\n"
                    "验证码 5 分钟内有效。如非本人操作，请忽略此邮件。"
                ),
                to=[candidate.primary_email],
            )
            if accepted != 1:
                raise RuntimeError("SMTP backend did not accept receipt recovery OTP")
        except Exception as exc:
            cache.delete(_challenge_cache_key(challenge_id))
            logger.exception(
                "HR04 receipt recovery delivery failed candidate_uid=%s",
                candidate.candidate_uid,
            )
            raise PublicPortalError(
                "RECEIPT_RECOVERY_UNAVAILABLE", "验证码发送失败，请稍后重试", 503
            ) from exc
    return challenge_id


def _verify_receipt_recovery_challenge(campaign, *, challenge_id, otp):
    from hr_recruitment.models import HrRecruitmentCandidate

    challenge_id = str(challenge_id or "").strip()
    otp = str(otp or "").strip()
    if not challenge_id or len(otp) != 6 or not otp.isdigit():
        raise PublicPortalError("OTP_INVALID", "验证码不正确或已失效", 422)
    key = _challenge_cache_key(challenge_id)
    payload = cache.get(key)
    if not isinstance(payload, dict):
        raise PublicPortalError("OTP_EXPIRED", "验证码已过期，请重新获取", 422)
    if (
        payload.get("tenant_id") != int(campaign.tenant_id)
        or time.time() > float(payload.get("expires_at") or 0)
    ):
        cache.delete(key)
        raise PublicPortalError("OTP_EXPIRED", "验证码已过期，请重新获取", 422)

    attempts = int(payload.get("attempts") or 0) + 1
    payload["attempts"] = attempts
    if attempts > PUBLIC_RECEIPT_OTP_MAX_ATTEMPTS or not constant_time_compare(
        payload.get("otp_hash", ""), _challenge_otp_hash(challenge_id, otp)
    ):
        if attempts >= PUBLIC_RECEIPT_OTP_MAX_ATTEMPTS:
            cache.delete(key)
        else:
            remaining = max(1, int(float(payload["expires_at"]) - time.time()))
            cache.set(key, payload, timeout=remaining)
        raise PublicPortalError("OTP_INVALID", "验证码不正确或已失效", 422)

    candidate_uid = payload.get("candidate_uid")
    if not candidate_uid:
        cache.delete(key)
        raise PublicPortalError("OTP_INVALID", "验证码不正确或已失效", 422)
    candidate = HrRecruitmentCandidate.objects.filter(
        tenant_id=campaign.tenant_id,
        candidate_uid=candidate_uid,
        status=CandidateStatus.ACTIVE,
    ).first()
    cache.delete(key)
    if candidate is None:
        raise PublicPortalError("OTP_INVALID", "验证码不正确或已失效", 422)
    return _issue_candidate_receipt(candidate)


def _issue_candidate_receipt(candidate) -> str:
    return signing.dumps(
        {
            "candidate_uid": candidate.candidate_uid,
            "tenant_id": int(candidate.tenant_id),
        },
        salt=PUBLIC_RECEIPT_SALT,
        compress=True,
    )


def _read_candidate_receipt(value: str) -> dict:
    if not value:
        raise ValueError("缺少报名查询凭证")
    try:
        payload = signing.loads(
            value,
            salt=PUBLIC_RECEIPT_SALT,
            max_age=getattr(
                settings,
                "HR04_PUBLIC_RECEIPT_MAX_AGE_SECONDS",
                180 * 24 * 60 * 60,
            ),
        )
    except signing.SignatureExpired as exc:
        raise ValueError("报名查询凭证已过期") from exc
    except signing.BadSignature as exc:
        raise ValueError("报名查询凭证无效") from exc
    if not isinstance(payload, dict) or not payload.get("candidate_uid") or not payload.get("tenant_id"):
        raise ValueError("报名查询凭证无效")
    return payload


def _resolve_campaign(token: str) -> HrRecruitmentCampaign | None:
    """A0：由公开 token 解析 campaign（含 tenant），禁止客户端传 tenant_id。"""
    return HrRecruitmentCampaign.objects.filter(
        public_token=token,
        status__in=[CampaignStatus.PUBLISHED, CampaignStatus.OPEN, CampaignStatus.RESULT_PROCESSING],
    ).first()


def _privacy_notice_context(campaign):
    """Return one server-owned privacy notice for both public templates."""
    school_name = "本招聘单位"
    if apps.is_installed("base"):
        from base.models import Company

        school_name = (
            Company.objects.filter(pk=campaign.tenant_id)
            .values_list("company", flat=True)
            .first()
            or school_name
        )
    return {
        "privacy_school_name": school_name,
        "privacy_notice_version": getattr(
            settings, "HR04_PRIVACY_NOTICE_VERSION", "2026-01"
        ),
        "privacy_retention_days": getattr(
            settings, "HR04_CANDIDATE_RETENTION_DAYS", 730
        ),
        "privacy_contact": getattr(
            settings, "HR04_PRIVACY_CONTACT", "招聘公告公布的联系方式"
        ),
    }


def _handle(request, exc):
    if isinstance(exc, PublicPortalError):
        return error(request, exc.code, exc.message, exc.status)
    if isinstance(exc, Hr04ApiError):
        return error(request, exc.code, exc.message, exc.status_code)
    if isinstance(exc, CandidateServiceError):
        return error(request, exc.code, exc.message, exc.http_status)
    if isinstance(exc, ApplicationServiceError):
        return error(request, exc.code, exc.message, exc.http_status)
    if isinstance(exc, json.JSONDecodeError):
        return error(request, "INVALID_JSON", "请求体不是有效 JSON", 400)
    if isinstance(exc, (TypeError, ValueError)):
        return error(request, "INVALID_REQUEST", str(exc), 422)
    return error(request, "INTERNAL_ERROR", "服务器内部错误", 500)


@require_GET
def public_campaign(request, token):
    """公开门户岗位列表页（HTML 默认；?format=json 返回岗位 JSON 供 JS 加载）。"""
    campaign = _resolve_campaign(token)
    if campaign is None:
        return error(request, "CAMPAIGN_NOT_FOUND", "招聘项目不存在或未开放", 404)
    if request.GET.get("format") == "json":
        positions = HrRecruitmentPosition.objects.filter(
            tenant_id=campaign.tenant_id, campaign_id=campaign
        ).exclude(status__in=["DRAFT", "CANCELLED"])
        return ok(
            request,
            {
                "campaign": {
                    "title": campaign.title,
                    "description": campaign.description,
                },
                "positions": [
                    {
                        "id": str(p.id),
                        "slug": p.public_slug,
                        "post_catalog_name": p.post_catalog_name,
                        "organization_name": p.organization_name,
                        "description": p.description,
                        "max_hires": p.max_hires,
                        "status": p.status,
                    }
                    for p in positions
                ],
            },
        )
    from django.shortcuts import render

    context = {"token": token, "campaign": campaign}
    context.update(_privacy_notice_context(campaign))
    return render(request, "hr/recruitment/portal/campaign.html", context)


@require_GET
def public_position(request, token, position_slug):
    campaign = _resolve_campaign(token)
    if campaign is None:
        return error(request, "CAMPAIGN_NOT_FOUND", "招聘项目不存在或未开放", 404)
    position = HrRecruitmentPosition.objects.filter(
        tenant_id=campaign.tenant_id,
        campaign_id=campaign,
        public_slug=position_slug,
    ).exclude(status__in=["DRAFT", "CANCELLED"]).first()
    if position is None:
        return error(request, "POSITION_NOT_FOUND", "岗位不存在", 404)
    return ok(
        request,
        {
            "id": str(position.id),
            "post_catalog_name": position.post_catalog_name,
            "organization_name": position.organization_name,
            "description": position.description,
            "planned_headcount": position.planned_headcount,
            "status": position.status,
        },
    )


@csrf_exempt
@require_http_methods(["POST"])
def public_apply(request, token):
    """
    公开提交申请（幂等）。

    A0：token 解析学校；body 不得含 tenant_id。
    流程：创建/复用候选 → save draft → submit（冻结版本 + ledger + application_no）。

    候选复用硬规则（总册 §23/§30.1）：
    - 仅凭 email 的 POSSIBLE_MATCH 一律不复用（防冒用他人邮箱报名）；
    - 只有身份证 hash EXACT_MATCH 或 email+mobile 双因子匹配才复用既有候选。

    幂等（§49）：同候选+同岗位已存在申请时——DRAFT 继续完成 submit；SUBMITTED+ 视为重放直接返回。
    """
    if _rate_limited(request, scope="apply"):
        return _rate_limit_response(request)
    campaign = _resolve_campaign(token)
    if campaign is None:
        return error(request, "CAMPAIGN_NOT_FOUND", "招聘项目不存在或未开放", 404)
    try:
        body = _json_object(request)
        idempotency_key = (get_idempotency_key(request) or "").strip()
        if not idempotency_key:
            return error(
                request,
                "IDEMPOTENCY_KEY_REQUIRED",
                "提交报名必须携带 Idempotency-Key，请刷新页面后重试",
                422,
            )
        if len(idempotency_key) > 128:
            return error(request, "IDEMPOTENCY_KEY_INVALID", "Idempotency-Key 过长", 422)
        now = timezone.now()
        if campaign.status != CampaignStatus.OPEN:
            return error(request, "CAMPAIGN_NOT_OPEN", "当前招聘项目未开放报名", 409)
        if campaign.application_open_at and now < campaign.application_open_at:
            return error(request, "APPLICATION_NOT_STARTED", "报名尚未开始", 409)
        if campaign.application_close_at and now > campaign.application_close_at:
            return error(request, "APPLICATION_CLOSED", "报名已截止", 409)
        position_id = body.get("position_id")
        position = HrRecruitmentPosition.objects.filter(
            tenant_id=campaign.tenant_id, id=position_id, campaign_id=campaign
        ).first()
        if position is None:
            return error(request, "POSITION_NOT_FOUND", "岗位不存在", 404)
        if position.status != "OPEN":
            return error(request, "POSITION_NOT_OPEN", "该岗位未在开放报名", 409)

        legal_name = body.get("legal_name")
        primary_email = (body.get("primary_email") or "").strip().lower()
        primary_mobile = (body.get("primary_mobile") or "").strip()
        national_id = body.get("national_id")
        if not legal_name or not primary_email or not primary_mobile:
            return error(request, "INVALID_REQUEST", "姓名、手机号码和邮箱均为必填项", 422)
        if _rate_limited(
            request,
            scope="apply",
            identity=f"{campaign.tenant_id}|{primary_email}|{primary_mobile}",
            identity_limit=PUBLIC_APPLY_IDENTITY_LIMIT,
            include_ip=False,
        ):
            return _rate_limit_response(request)
        if body.get("privacy_consent") is not True:
            return error(
                request,
                "PRIVACY_CONSENT_REQUIRED",
                "请阅读并同意招聘个人信息处理告知后再报名",
                422,
            )

        from hr_recruitment.models import HrRecruitmentCandidate

        candidate = None
        # 1) 身份证 hash EXACT_MATCH（最可信）才复用
        if national_id:
            match = CandidateService(tenant_id=campaign.tenant_id).identity_match(
                national_id=national_id
            )
            if match["match_result"] == "EXACT_MATCH" and match["matches"]:
                candidate = HrRecruitmentCandidate.objects.get(id=match["matches"][0]["id"])
        # 2) email+mobile 双因子（仅凭 email 不复用）
        if candidate is None and primary_mobile:
            candidate = HrRecruitmentCandidate.objects.filter(
                tenant_id=campaign.tenant_id,
                primary_email__iexact=primary_email,
                primary_mobile=primary_mobile,
            ).first()

        if candidate is not None and candidate.status != CandidateStatus.ACTIVE:
            return error(
                request,
                "CANDIDATE_NOT_AVAILABLE",
                "当前候选人状态不可报名，请联系招聘单位核实",
                409,
            )

        candidate_service = CandidateService(tenant_id=campaign.tenant_id, actor="public")
        if candidate is None:
            candidate = candidate_service.create_candidate(
                legal_name=legal_name,
                preferred_name=body.get("preferred_name", ""),
                primary_email=primary_email,
                primary_mobile=primary_mobile,
                national_id=national_id,
                source="PUBLIC_PORTAL",
            )

        retention_days = int(
            getattr(settings, "HR04_CANDIDATE_RETENTION_DAYS", 730)
        )
        if retention_days < 1:
            return error(request, "RETENTION_POLICY_INVALID", "候选人保留期限配置无效", 500)
        candidate = candidate_service.record_consent(
            str(candidate.id),
            consent_version=getattr(
                settings,
                "HR04_PRIVACY_NOTICE_VERSION",
                "2026-01",
            ),
            retention_until=timezone.localdate() + timedelta(days=retention_days),
        )

        application_service = ApplicationService(tenant_id=campaign.tenant_id, actor="")
        existing = HrJobApplication.objects.filter(
            tenant_id=campaign.tenant_id,
            candidate_id_id=candidate.id,
            recruitment_position_id_id=position.id,
            is_active=True,
        ).first()
        if existing is not None:
            if existing.canonical_status == ApplicationCanonicalStatus.DRAFT:
                # 上次在 draft 后中断：继续完成 submit（§49 公开报名可靠性）
                app = application_service.submit(
                    application_id=str(existing.id),
                    idempotency_key=idempotency_key,
                )
                return ok(
                    request,
                    {
                        "application_no": app.application_no,
                        "canonical_status": app.canonical_status,
                        "candidate_uid": candidate.candidate_uid,
                        "access_token": _issue_candidate_receipt(candidate),
                    },
                    status=201,
                )
            # SUBMITTED 及以上仍通过服务绑定/校验幂等键，防止同一个 key
            # 被不同候选人或不同申请复用后返回他人申请编号。
            existing = application_service.submit(
                application_id=str(existing.id),
                idempotency_key=idempotency_key,
            )
            return ok(
                request,
                {
                    "application_no": existing.application_no,
                    "canonical_status": existing.canonical_status,
                    "candidate_uid": candidate.candidate_uid,
                    "access_token": _issue_candidate_receipt(candidate),
                    "replayed": True,
                },
                status=201,
            )
        draft = application_service.save_draft(
            candidate_id=str(candidate.id),
            recruitment_position_id=str(position.id),
            form_data=body.get("form_data"),
        )
        app = application_service.submit(
            application_id=str(draft.id),
            idempotency_key=idempotency_key,
        )
        return ok(
            request,
            {
                "application_no": app.application_no,
                "canonical_status": app.canonical_status,
                "candidate_uid": candidate.candidate_uid,
                "access_token": _issue_candidate_receipt(candidate),
            },
            status=201,
        )
    except Exception as exc:  # noqa: BLE001
        return _handle(request, exc)


@csrf_exempt
@require_http_methods(["POST"])
def public_my_applications(request):
    """
    候选人本人申请查询（self scope，P0 防跨租户泄漏）。

    身份因子：必须使用报名成功时签发的限时查询凭证，并再次核对 email+mobile。
    凭证同时绑定 tenant 和 candidate_uid，禁止跨校枚举候选记录。
    """
    if _rate_limited(request, scope="query"):
        return _rate_limit_response(request)
    try:
        body = _json_object(request)
        primary_email = (body.get("primary_email") or "").strip().lower()
        primary_mobile = (body.get("primary_mobile") or "").strip()
        access_token = body.get("access_token") or ""
        if not primary_email or not primary_mobile or not access_token:
            return error(
                request,
                "INSUFFICIENT_IDENTITY",
                "查询本人申请需要报名查询凭证、邮箱和手机号",
                422,
            )
        if _rate_limited(
            request,
            scope="query",
            identity=access_token,
            identity_limit=PUBLIC_RECEIPT_QUERY_LIMIT,
            include_ip=False,
        ):
            return _rate_limit_response(request)
        receipt = _read_candidate_receipt(access_token)
        from hr_recruitment.models import HrRecruitmentCandidate

        candidate = HrRecruitmentCandidate.objects.filter(
            tenant_id=receipt["tenant_id"],
            candidate_uid=receipt["candidate_uid"],
            status=CandidateStatus.ACTIVE,
            primary_email__iexact=primary_email,
            primary_mobile=primary_mobile,
        ).first()
        if candidate is None:
            return ok(request, {"applications": []})
        applications = HrJobApplication.objects.filter(
            tenant_id=candidate.tenant_id, candidate_id=candidate
        ).select_related("recruitment_position_id")
        return ok(
            request,
            {
                "candidate_uid": candidate.candidate_uid,
                "applications": [
                    {
                        "application_no": a.application_no,
                        "canonical_status": a.canonical_status,
                        "canonical_status_label": status_label(
                            APPLICATION_STATUS_LABELS, a.canonical_status
                        ),
                        "position": a.recruitment_position_id.post_catalog_name
                        if a.recruitment_position_id
                        else "",
                        "submitted_at": a.submitted_at.isoformat() if a.submitted_at else None,
                    }
                    for a in applications
                ],
            },
        )
    except (TypeError, ValueError) as exc:
        return error(request, "INVALID_RECEIPT", str(exc), 422)
    except Exception as exc:  # noqa: BLE001
        return _handle(request, exc)


@csrf_exempt
@require_POST
def public_request_receipt_recovery(request, token):
    """Send a short-lived OTP to recover the tenant-bound query receipt."""

    if _rate_limited(request, scope="receipt-recovery"):
        return _rate_limit_response(request)
    campaign = _resolve_campaign(token)
    if campaign is None:
        return error(request, "CAMPAIGN_NOT_FOUND", "招聘项目不存在或未开放", 404)
    try:
        body = _json_object(request)
        challenge_id = _issue_receipt_recovery_challenge(
            request,
            campaign,
            email=body.get("primary_email"),
            mobile=body.get("primary_mobile"),
        )
        return ok(
            request,
            {
                "challenge_id": challenge_id,
                "expires_in": PUBLIC_RECEIPT_OTP_TTL_SECONDS,
                "message": "若报名信息匹配，验证码已发送至报名邮箱",
            },
        )
    except Exception as exc:  # noqa: BLE001
        return _handle(request, exc)


@csrf_exempt
@require_POST
def public_verify_receipt_recovery(request, token):
    """Verify the recovery OTP and return a fresh signed query receipt."""

    if _rate_limited(request, scope="receipt-recovery-verify"):
        return _rate_limit_response(request)
    campaign = _resolve_campaign(token)
    if campaign is None:
        return error(request, "CAMPAIGN_NOT_FOUND", "招聘项目不存在或未开放", 404)
    try:
        body = _json_object(request)
        access_token = _verify_receipt_recovery_challenge(
            campaign,
            challenge_id=body.get("challenge_id"),
            otp=body.get("otp"),
        )
        return ok(request, {"access_token": access_token})
    except Exception as exc:  # noqa: BLE001
        return _handle(request, exc)
