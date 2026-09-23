"""School-owned onboarding configuration, on the existing HR05 template models.

A published version is materialized once, sealed and pinned to NEW cases only.
No state-machine transition or formal personnel rule is configurable here.
"""
from __future__ import annotations

from datetime import date
import copy
import re

from django.db import IntegrityError, transaction
from django.db.models import Max
from django.utils import timezone

from hr_onboarding.api.exceptions import (
    Hr05ApiError, NotFoundError, PermissionDeniedError, VersionConflictError,
)
from hr_onboarding.constants import (
    BlockingLevel, CaseStatus, EmploymentType, StaffCategoryCode,
    ResponsibleRole, MaterialBlockingPhase,
)
from hr_onboarding.models import (
    HrOnboardingTemplate, HrOnboardingTemplateVersion,
    HrOnboardingTaskDefinition, HrOnboardingStageDefinition,
    HrOnboardingMaterialRequirement, HrOnboardingMaterial,
    HrOnboardingTaskInstance, HrOnboardingAuditEvent, HrOnboardingCase,
)
from hr_onboarding.services.idempotency_service import (
    DurableIdempotencyService, canonical_request_hash,
)
from hr_onboarding.services.workflow_service import assert_permission, permitted

SCHEMA = 'hr05.school-template.1'
CODE = re.compile(r'^[A-Z][A-Z0-9_]{0,63}$')
MANAGE = 'hr05.template.manage'
PUBLISH = 'hr05.template.publish'
FORMATS = {'pdf', 'png', 'jpg', 'jpeg', 'docx', 'xlsx'}
PRE_BIND_STATES = {CaseStatus.CREATED, CaseStatus.PREPARING, CaseStatus.READY_TO_REPORT}


class TemplateConfigurationError(Hr05ApiError):
    status_code = 422
    code = 'TEMPLATE_CONFIGURATION_INVALID'


def _err(message):
    raise TemplateConfigurationError(message)


def _text(value, name, limit=200, *, required=True):
    if not isinstance(value, str) or len(value) > limit:
        _err(f'{name}须为不超过{limit}字的文本')
    value = value.strip()
    if required and not value:
        _err(f'请填写{name}')
    return value


def _code(value, name):
    value = _text(value, name, 64)
    if not CODE.fullmatch(value):
        _err(f'{name}使用大写字母开头，只含大写字母、数字或下划线')
    return value


def _integer(value, name, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        _err(f'{name}须为{minimum}至{maximum}的整数')
    return value


def _boolean(value, name):
    if type(value) is not bool:
        _err(f'{name}须为布尔值')
    return value


def _enum(value, allowed, name):
    if value not in allowed:
        _err(f'{name}不属于已有业务枚举')
    return value


def _keys(value, allowed, name):
    if not isinstance(value, dict) or set(value) - set(allowed):
        _err(f'{name}包含未知字段或不是对象')


def _strings(value, name, *, allowed=None, max_count=100):
    if not isinstance(value, list) or len(value) > max_count:
        _err(f'{name}须为最多{max_count}项的列表')
    result = [_text(x, name, 64) for x in value]
    if len(set(result)) != len(result):
        _err(f'{name}有重复项')
    if allowed is not None and any(x not in allowed for x in result):
        _err(f'{name}包含不支持的选项')
    return sorted(result)


def normalize_plan(data):
    """Only the implemented, manually handled configuration subset is accepted.

    Unknown fields (tenant, actor, automatic handlers, conditional JSON, policy
    bypasses) are not silently dropped. Dates use [from,to), explicitly in UI.
    """
    _keys(data, {'code', 'name', 'effective_from', 'effective_to', 'scope', 'tasks', 'materials', 'note'}, '方案')
    result = {'code': _code(data.get('code'), '方案编号'),
              'name': _text(data.get('name'), '方案名称'),
              'note': _text(data.get('note', ''), '制度依据/说明', 2000, required=False)}
    try:
        start = date.fromisoformat(data.get('effective_from', ''))
        end = date.fromisoformat(data['effective_to']) if data.get('effective_to') else None
    except (ValueError, TypeError):
        _err('请填写有效日期（YYYY-MM-DD）')
    if end and end <= start:
        _err('截止日期不含当天，必须晚于开始日期')
    result.update(effective_from=start.isoformat(), effective_to=end.isoformat() if end else None)
    scope = data.get('scope', {})
    _keys(scope, {'staff_categories', 'employment_types'}, '适用范围')
    result['scope'] = {
        'staff_categories': _strings(scope.get('staff_categories', []), '人员类别', allowed=StaffCategoryCode.values),
        'employment_types': _strings(scope.get('employment_types', []), '用工性质', allowed=EmploymentType.values),
    }
    tasks = data.get('tasks', [])
    mats = data.get('materials', [])
    if not isinstance(tasks, list) or len(tasks) > 100 or not isinstance(mats, list) or len(mats) > 100:
        _err('任务和材料分别最多100项')
    result['tasks'] = []
    for i, t in enumerate(tasks, 1):
        _keys(t, {'code', 'title', 'responsible_role', 'blocking_level', 'available_offset_days',
                  'due_offset_days', 'prerequisite_codes', 'candidate_visible'}, f'任务{i}')
        available = _integer(t.get('available_offset_days', 0), '可办理偏移天数', -365, 3650)
        due = _integer(t.get('due_offset_days', 0), '截止偏移天数', -365, 3650)
        if due < available:
            _err(f'任务{i}截止时间不能早于可办理时间')
        result['tasks'].append({
            'code': _code(t.get('code'), '任务编号'), 'title': _text(t.get('title'), '任务名称'),
            'responsible_role': _enum(t.get('responsible_role', 'RESPONSIBLE_HR'), ResponsibleRole.values, '责任角色'),
            'blocking_level': _enum(t.get('blocking_level', 'NON_BLOCKING'), BlockingLevel.values, '阻塞类型'),
            'available_offset_days': available, 'due_offset_days': due,
            'prerequisite_codes': _strings(t.get('prerequisite_codes', []), '前置任务编号'),
            'candidate_visible': _boolean(t.get('candidate_visible', True), '本人可见'),
        })
    result['materials'] = []
    for i, m in enumerate(mats, 1):
        _keys(m, {'material_type', 'label', 'required', 'blocking_phase', 'allowed_formats', 'max_size_mb'}, f'材料{i}')
        result['materials'].append({
            'material_type': _code(m.get('material_type'), '材料编号'), 'label': _text(m.get('label'), '材料名称'),
            'required': _boolean(m.get('required', True), '是否必交'),
            'blocking_phase': _enum(m.get('blocking_phase', 'ACTIVATION'), MaterialBlockingPhase.values, '核验阶段'),
            'allowed_formats': _strings(m.get('allowed_formats', ['pdf', 'png', 'jpg', 'jpeg']), '文件格式', allowed=FORMATS),
            'max_size_mb': _integer(m.get('max_size_mb', 10), '单文件上限MiB', 1, 50),
        })
        if not result['materials'][-1]['allowed_formats']:
            _err('材料必须指定文件格式，不允许空白名单')
    for rows, key, label in [(result['tasks'], 'code', '任务'), (result['materials'], 'material_type', '材料')]:
        if len({x[key] for x in rows}) != len(rows):
            _err(f'{label}编号不能重复')
    return result


def validate_plan(plan):
    """Read-only publish checks, also used for preview. Draft may have a bad DAG."""
    errors, warnings = [], []
    if not plan['tasks'] and not plan['materials']:
        errors.append('方案没有任何任务或材料，不能发布空办理方案')
    if not plan['note']:
        errors.append('请填写制度依据/配置说明，以便发布人核对')
    graph = {t['code']: t['prerequisite_codes'] for t in plan['tasks']}
    missing = sorted({p for deps in graph.values() for p in deps if p not in graph})
    if missing:
        errors.append('前置任务不存在：' + '、'.join(missing))
    visiting, visited = set(), set()
    def visit(code):
        if code in visiting:
            return False
        if code in visited or code not in graph:
            return True
        visiting.add(code)
        for p in graph[code]:
            if not visit(p):
                return False
        visiting.remove(code); visited.add(code)
        return True
    if any(not visit(c) for c in graph):
        errors.append('前置任务存在循环依赖，必须先拆开循环')
    if not any(plan['scope'].values()):
        warnings.append('适用范围为空表示本校全部人员类别和用工性质；请确认这符合制度')
    warnings.append('任务时间沿用原系统：以实际生成任务的时刻为偏移基准，不等同于预计报到日')
    warnings.append('责任角色不授予账号权限；生成后仍需在协同任务中分派已有权限的实际责任人')
    return {'valid': not errors, 'errors': errors, 'warnings': warnings}


def _snapshot(version):
    snap = version.snapshot_json or {}
    if snap.get('schema') != SCHEMA:
        _err('这是旧版模板；保留原办理，不允许用本编辑器覆盖旧结构')
    if snap.get('plan_hash') != canonical_request_hash(snap.get('plan')):
        _err('方案内容与校验不一致，请停止使用并核查')
    return snap


def _definition_projection(version):
    return {
        'tasks': list(HrOnboardingTaskDefinition.objects.filter(template_version=version).order_by('sequence', 'code').values(
            'tenant_id','code','title','category','responsible_role','blocking_level','available_offset_days',
            'due_offset_days','prerequisite_codes','candidate_visible','completion_type','automation_handler','sequence')),
        'materials': list(HrOnboardingMaterialRequirement.objects.filter(template_version=version).order_by('material_type').values(
            'tenant_id','material_type','label','required','blocking_phase','allowed_formats','max_size',
            'verification_required','condition_json','destination_domain','retention_policy','reuse_policy')),
        'stages': list(HrOnboardingStageDefinition.objects.filter(template_version=version).order_by('sequence','code').values(
            'tenant_id','code','title','sequence','is_final')),
    }


def verify_school_template(version, tenant_id):
    """Legacy versions retain old behavior; new versions reject definition drift."""
    if version is None:
        return
    if version.tenant_id != tenant_id or version.template.tenant_id != tenant_id:
        _err('方案版本与学校归属不一致')
    if (version.snapshot_json or {}).get('schema') != SCHEMA:
        return
    snap = _snapshot(version)
    if version.status not in {'ACTIVE', 'RETIRED'}:
        _err('草稿不可用于实际办理')
    if not snap.get('published_by') or not snap.get('definition_hash'):
        _err('方案缺少正式发布依据')
    if snap['definition_hash'] != canonical_request_hash(_definition_projection(version)):
        _err('已发布方案定义发生变化，停止生成/办理并核查原版本')
    if (version.effective_from.isoformat() if version.effective_from else None) != snap['plan']['effective_from'] or \
       (version.effective_to.isoformat() if version.effective_to else None) != snap['plan']['effective_to']:
        _err('已发布方案有效期被修改')


def projection(version):
    snap = _snapshot(version)
    if version.status != 'DRAFT':
        verify_school_template(version, version.tenant_id)
    return {'id': str(version.id), 'template_id': str(version.template_id), 'version_no': version.version_no,
            'status': version.status, 'etag': canonical_request_hash(snap), 'plan': snap['plan'],
            'checks': validate_plan(snap['plan']), 'editors': snap['editors'],
            'published_by': snap.get('published_by'), 'published_at': snap.get('published_at'),
            'bound_cases': version.cases.count()}


class SchoolTemplateService:
    def __init__(self, *, tenant_id, user, request_id=''):
        if isinstance(tenant_id, bool) or not tenant_id:
            raise PermissionDeniedError('缺少可信学校上下文')
        self.tenant_id = int(tenant_id); self.user = user; self.request_id = str(request_id)[:64]

    def _read_permission(self):
        if not (permitted(self.user, MANAGE) or permitted(self.user, PUBLISH)):
            raise PermissionDeniedError('没有校本入职方案配置/发布权限')

    def _get(self, version_id, lock=False):
        qs = HrOnboardingTemplateVersion.objects.filter(tenant_id=self.tenant_id, template__tenant_id=self.tenant_id)
        if lock:
            qs = qs.select_for_update()
        obj = qs.select_related('template').filter(pk=version_id).first()
        if not obj:
            raise NotFoundError('方案版本不存在或无权访问')
        return obj

    def _audit(self, action, version, before='', reason='', case_id=None):
        return HrOnboardingAuditEvent.objects.create(tenant_id=self.tenant_id, actor_user_id=self.user.id,
            case_id=case_id, action=action, business_type='SCHOOL_TEMPLATE', business_id=str(version.id),
            before_snapshot_ref=before, after_snapshot_ref=canonical_request_hash(version.snapshot_json),
            reason=reason, request_id=self.request_id)

    def _claim(self, op, key, payload):
        svc = DurableIdempotencyService(tenant_id=self.tenant_id, operation=op)
        claim = svc.claim(idempotency_key=key, request_payload={'actor': self.user.id, **payload})
        return svc, claim

    @staticmethod
    def _finish(svc, claim, version, result):
        svc.succeed(claim.record, authority_type='HrOnboardingTemplateVersion', authority_id=version.id, response_summary=result)
        return result

    @staticmethod
    def _replay(claim):
        return {**claim.record.response_summary, 'replayed': True}

    def list(self, page=1, page_size=20):
        self._read_permission()
        page = _integer(page, '页码', 1, 1000000); page_size = _integer(page_size, '页大小', 1, 50)
        qs = HrOnboardingTemplateVersion.objects.filter(tenant_id=self.tenant_id, template__tenant_id=self.tenant_id).select_related('template').order_by('-created_at', '-version_no')
        count = qs.count(); rows = list(qs[(page-1)*page_size:page*page_size])
        items = []
        for v in rows:
            managed = (v.snapshot_json or {}).get('schema') == SCHEMA
            plan = (v.snapshot_json or {}).get('plan', {}) if managed else {}
            items.append({'id': str(v.id), 'code': v.template.code, 'name': plan.get('name', v.template.name),
                'version_no': v.version_no, 'status': v.status, 'managed': managed})
        return {'items': items, 'page': page, 'pageSize': page_size, 'total': count, 'hasNext': page*page_size<count}

    def detail(self, version_id):
        self._read_permission(); return projection(self._get(version_id))

    @transaction.atomic
    def save(self, *, plan, idempotency_key, version_id=None, etag=None):
        assert_permission(self.user, MANAGE)
        plan = normalize_plan(plan)
        svc, claim = self._claim('SCHOOL_TEMPLATE_SAVE', idempotency_key,
            {'plan': plan, 'version_id': str(version_id) if version_id else None, 'etag': etag})
        if claim.is_replay:
            return self._replay(claim)
        before = ''
        if version_id:
            v = self._get(version_id, lock=True); old = _snapshot(v); before = canonical_request_hash(old)
            if v.status != 'DRAFT':
                _err('已发布方案不能修改，请复制为新草稿')
            if not etag or etag != before:
                raise VersionConflictError('草稿已变化，请重读后比较再保存')
            if plan['code'] != v.template.code:
                _err('同一草稿不能改变方案编号')
            editors = sorted(set(old['editors']) | {self.user.id}); revision = old['revision'] + 1
        else:
            try:
                with transaction.atomic():
                    tpl, _ = HrOnboardingTemplate.objects.get_or_create(tenant_id=self.tenant_id,
                        code=plan['code'], defaults={'name': plan['name']})
            except IntegrityError:
                tpl = HrOnboardingTemplate.objects.get(tenant_id=self.tenant_id, code=plan['code'])
            tpl = HrOnboardingTemplate.objects.select_for_update().get(pk=tpl.id, tenant_id=self.tenant_id)
            number = (tpl.versions.aggregate(n=Max('version_no'))['n'] or 0) + 1
            v = HrOnboardingTemplateVersion(tenant_id=self.tenant_id, template=tpl, version_no=number)
            editors = [self.user.id]; revision = 1
        v.effective_from = date.fromisoformat(plan['effective_from'])
        v.effective_to = date.fromisoformat(plan['effective_to']) if plan['effective_to'] else None
        v.snapshot_json = {'schema': SCHEMA, 'plan': plan, 'plan_hash': canonical_request_hash(plan),
                           'editors': editors, 'revision': revision}
        v.save()
        receipt = self._audit('SCHOOL_TEMPLATE_DRAFT_SAVED', v, before)
        return self._finish(svc, claim, v, {'version': projection(v), 'receipt': str(receipt.id), 'replayed': False})

    @transaction.atomic
    def publish(self, *, version_id, etag, reason, idempotency_key):
        assert_permission(self.user, PUBLISH)
        reason = _text(reason, '发布依据', 2000)
        # Parent lock serializes publication of sibling versions for MySQL too.
        stub = self._get(version_id)
        HrOnboardingTemplate.objects.select_for_update().get(pk=stub.template_id, tenant_id=self.tenant_id)
        v = self._get(version_id, lock=True)
        svc, claim = self._claim('SCHOOL_TEMPLATE_PUBLISH', idempotency_key, {'version_id': str(v.id), 'etag': etag, 'reason': reason})
        if claim.is_replay:
            return self._replay(claim)
        snap = copy.deepcopy(_snapshot(v)); before = canonical_request_hash(snap)
        if not etag or before != etag:
            raise VersionConflictError('发布内容已变化，请重新预览后发布')
        if v.status != 'DRAFT':
            _err('只有草稿可发布')
        if self.user.id in snap['editors']:
            raise PermissionDeniedError('任何参与编辑的经办人都不能发布该版本，须另一名授权人员复核')
        plan = normalize_plan(snap['plan']); checks = validate_plan(plan)
        if not checks['valid']:
            raise TemplateConfigurationError('方案校验未通过', details=checks)
        peers = HrOnboardingTemplateVersion.objects.filter(template_id=v.template_id, tenant_id=self.tenant_id, status='ACTIVE').exclude(pk=v.id)
        for peer in peers:
            if (not peer.effective_to or peer.effective_to > v.effective_from) and (not v.effective_to or not peer.effective_from or peer.effective_from < v.effective_to):
                _err('同一方案已有生效期重叠的版本；须明确停用旧版本（旧单继续旧版），不能自动覆盖')
        if v.task_definitions.exists() or v.material_requirements.exists() or v.stage_definitions.exists():
            _err('草稿已有异常实体定义，请先核查')
        for i, t in enumerate(plan['tasks']):
            HrOnboardingTaskDefinition.objects.create(tenant_id=self.tenant_id, template_version=v,
                **t, sequence=i, completion_type='MANUAL', automation_handler='', category='')
        for m in plan['materials']:
            m = dict(m); max_size = m.pop('max_size_mb') * 1024 * 1024
            HrOnboardingMaterialRequirement.objects.create(tenant_id=self.tenant_id, template_version=v,
                **m, max_size=max_size, verification_required=True, reuse_policy='REVERIFY')
        snap.update(published_by=self.user.id, published_at=timezone.now().isoformat(), publish_reason=reason,
                    definition_hash=canonical_request_hash(_definition_projection(v)))
        v.snapshot_json = snap; v.status = 'ACTIVE'; v.save(update_fields=['snapshot_json','status'])
        v.template.status = 'ACTIVE'; v.template.save(update_fields=['status','updated_at'])
        receipt = self._audit('SCHOOL_TEMPLATE_PUBLISHED', v, before, reason)
        return self._finish(svc, claim, v, {'version': projection(v), 'receipt': str(receipt.id), 'replayed': False})

    @transaction.atomic
    def retire(self, *, version_id, etag, reason, idempotency_key):
        assert_permission(self.user, PUBLISH)
        reason = _text(reason, '停用原因', 2000)
        stub = self._get(version_id)
        HrOnboardingTemplate.objects.select_for_update().get(pk=stub.template_id, tenant_id=self.tenant_id)
        v = self._get(version_id, lock=True)
        svc, claim = self._claim('SCHOOL_TEMPLATE_RETIRE', idempotency_key, {'version_id': str(v.id), 'etag': etag, 'reason': reason})
        if claim.is_replay:
            return self._replay(claim)
        before = canonical_request_hash(_snapshot(v))
        if not etag or etag != before:
            raise VersionConflictError('方案内容已变化')
        if v.status != 'ACTIVE':
            _err('只有已发布版本可停用')
        verify_school_template(v, self.tenant_id)
        snap = copy.deepcopy(v.snapshot_json)
        snap.update(retired_by=self.user.id, retired_at=timezone.now().isoformat(), retire_reason=reason)
        v.snapshot_json = snap; v.status = 'RETIRED'; v.save(update_fields=['snapshot_json','status'])
        receipt = self._audit('SCHOOL_TEMPLATE_RETIRED', v, before, reason)
        return self._finish(svc, claim, v, {'version': projection(v), 'receipt': str(receipt.id), 'replayed': False})

    def _case(self, case_id, lock=False):
        qs = HrOnboardingCase.objects.filter(tenant_id=self.tenant_id)
        if lock:
            qs = qs.select_for_update()
        case = qs.filter(pk=case_id).first()
        if not case:
            raise NotFoundError('入职单不存在或无权访问')
        return case

    def _case_checks(self, v, case):
        p = _snapshot(v)['plan']; errors = []
        if v.status != 'ACTIVE': errors.append('方案不是已发布状态')
        else: verify_school_template(v, self.tenant_id)
        if case.template_version_id: errors.append('入职单已绑定版本，不允许更换已办依据')
        if case.status not in PRE_BIND_STATES: errors.append('仅报到前的未生效入职单可以绑定')
        if any((case.hr03_person_id,case.hr03_staff_master_id,case.hr03_employment_id,case.hr03_assignment_id)):
            errors.append('已存在正式人员关系，不允许重新绑定')
        if case.activation_status != 'NOT_STARTED': errors.append('已开始激活，不允许绑定新方案')
        if HrOnboardingMaterial.objects.filter(case_id=case.id).exists() or HrOnboardingTaskInstance.objects.filter(case_id=case.id).exists():
            errors.append('已产生材料或任务实例，不允许用新方案覆盖')
        when = case.expected_report_date
        if not when: errors.append('请先核定预计报到日期，再按该日期检查方案有效期')
        elif when < v.effective_from or (v.effective_to and when >= v.effective_to): errors.append('预计报到日不在方案有效期间')
        for key, value, label in [('staff_categories',case.staff_category,'人员类别'),('employment_types',case.employment_type,'用工性质')]:
            allowed = p['scope'][key]
            if allowed and value not in allowed: errors.append(f'{label}不匹配此方案')
        return errors

    def preview(self, *, version_id, case_id):
        self._read_permission(); assert_permission(self.user, 'hr05.case.view')
        v = self._get(version_id); case = self._case(case_id)
        return {'case_id': str(case.id), 'case_no': case.case_no, 'case_version': case.version,
                'eligible': not (errors := self._case_checks(v, case)), 'errors': errors,
                'version': projection(v), 'task_count': len(_snapshot(v)['plan']['tasks']),
                'material_count': len(_snapshot(v)['plan']['materials']),
                'note': '预览只读，不创建任务、材料或正式人员；绑定后仍要按原流程办理。'}

    @transaction.atomic
    def bind(self, *, version_id, case_id, case_version, etag, idempotency_key):
        assert_permission(self.user, MANAGE); assert_permission(self.user, 'hr05.case.create'); assert_permission(self.user, 'hr05.case.view')
        v = self._get(version_id, lock=True); case = self._case(case_id, lock=True)
        svc, claim = self._claim('SCHOOL_TEMPLATE_BIND', idempotency_key, {'version_id': str(v.id), 'case_id': str(case.id), 'case_version': case_version, 'etag': etag})
        if claim.is_replay: return self._replay(claim)
        if type(case_version) is not int or case.version != case_version:
            raise VersionConflictError('入职单已变化，请重新预览')
        if etag != canonical_request_hash(_snapshot(v)):
            raise VersionConflictError('方案已变化，请重新预览')
        errors = self._case_checks(v, case)
        if errors: raise TemplateConfigurationError('不能绑定此入职方案', details={'errors': errors})
        case.template_version = v; case.version += 1; case.save(update_fields=['template_version','version','updated_at'])
        from hr_onboarding.services.task_service import TaskService
        from hr_onboarding.services.material_service import ensure_materials_from_requirements
        task_count = TaskService(tenant_id=self.tenant_id, actor_user_id=self.user.id).instantiate_tasks(case)
        material_count = ensure_materials_from_requirements(case)
        receipt = self._audit('SCHOOL_TEMPLATE_BOUND', v, reason='报到前明确绑定已发布校本方案', case_id=case.id)
        return self._finish(svc, claim, v, {'case_id':str(case.id),'case_no':case.case_no,'case_version':case.version,
            'template_version_id':str(v.id),'tasks_created':task_count,'materials_created':material_count,
            'receipt':str(receipt.id),'replayed':False,
            'next_url':f'/hr/onboarding/collaboration?case_id={case.id}'})
