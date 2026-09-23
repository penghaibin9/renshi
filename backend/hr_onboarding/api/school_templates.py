"""Authenticated, CSRF-protected school-template operations."""
import json
from uuid import UUID
from django.views.decorators.http import require_GET, require_POST
from hr_onboarding.api import base
from hr_onboarding.api.exceptions import Hr05ApiError, PermissionDeniedError
from hr_onboarding.services.school_template_service import SchoolTemplateService


def _service(request):
    ctx = base.make_hr05_context(request)
    if ctx.scope.scope_type != 'SCHOOL':
        raise PermissionDeniedError('校本方案只允许学校级配置，不可借配置扩大院系范围')
    return SchoolTemplateService(tenant_id=ctx.tenant_id, user=request.user, request_id=base._request_id(request))


def _body(request, allowed):
    if len(request.body) > 262144:
        raise Hr05ApiError('方案请求过大')
    if request.content_type != 'application/json':
        raise Hr05ApiError('请使用 JSON 请求')
    try:
        data = json.loads(request.body or b'{}')
    except (ValueError, UnicodeError):
        raise Hr05ApiError('请求不是有效JSON')
    if not isinstance(data, dict) or set(data) - set(allowed):
        raise Hr05ApiError('请求字段不受支持')
    return data


def _run(request, callback):
    try:
        return base.ok(request, callback(_service(request)))
    except Exception as exc:
        return base.handle_hr05_error(request, exc)


@require_GET
def collection(request):
    def invoke(svc):
        try:
            page, size = int(request.GET.get('page', 1)), int(request.GET.get('pageSize', 20))
        except (TypeError, ValueError):
            raise Hr05ApiError('页码和页大小须为整数')
        return svc.list(page=page, page_size=size)
    return _run(request, invoke)


@require_GET
def detail(request, version_id):
    return _run(request, lambda s: s.detail(version_id))


@require_POST
def save(request):
    def invoke(svc):
        b = _body(request, {'plan','version_id','etag'})
        if b.get('version_id') is not None:
            try:
                b['version_id'] = str(UUID(str(b['version_id'])))
            except (ValueError, TypeError, AttributeError):
                raise Hr05ApiError('方案版本编号格式无效')
        return svc.save(plan=b.get('plan'), version_id=b.get('version_id'), etag=b.get('etag'),
                        idempotency_key=base.get_idempotency_key(request))
    return _run(request, invoke)


@require_POST
def publish(request, version_id):
    def invoke(svc):
        b = _body(request, {'etag','reason'})
        return svc.publish(version_id=version_id, etag=b.get('etag'), reason=b.get('reason'),
                           idempotency_key=base.get_idempotency_key(request))
    return _run(request, invoke)


@require_POST
def retire(request, version_id):
    def invoke(svc):
        b = _body(request, {'etag','reason'})
        return svc.retire(version_id=version_id, etag=b.get('etag'), reason=b.get('reason'),
                          idempotency_key=base.get_idempotency_key(request))
    return _run(request, invoke)


@require_GET
def preview(request, version_id, case_id):
    return _run(request, lambda s: s.preview(version_id=version_id, case_id=case_id))


@require_POST
def bind(request, version_id, case_id):
    def invoke(svc):
        b = _body(request, {'etag','case_version'})
        return svc.bind(version_id=version_id, case_id=case_id, etag=b.get('etag'),
                        case_version=b.get('case_version'), idempotency_key=base.get_idempotency_key(request))
    return _run(request, invoke)
