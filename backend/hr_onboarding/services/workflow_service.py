"""Task ownership and outcome-based onboarding, using the existing HR05 facts.

No generic workflow engine and no duplicate staff records. API commands lock the
case before the task, then commit the domain change, receipt and idempotency row
in one transaction. Readers never instantiate tasks or advance case states.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from django.contrib.auth import get_user_model
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q, Case, When, Value, IntegerField, F, OuterRef, Subquery
from django.utils import timezone
from django.db.models.functions import Coalesce

from hr_onboarding.api.exceptions import (
    Hr05ApiError, NotFoundError, PermissionDeniedError, VersionConflictError,
    InvalidStateTransitionError, TaskPrerequisiteNotMetError,
)
from hr_onboarding.api.labels import (
    label_for, TASK_STATUS_LABELS, RESPONSIBLE_ROLE_LABELS, BLOCKING_LEVEL_LABELS,
    CASE_STATUS_LABELS,
)
from hr_onboarding.constants import (
    TaskStatus as T, CaseStatus as C, BlockingLevel as B, MaterialStatus as M,
    MaterialBlockingPhase as P, RiskCode, TaskCompletionType,
)
from hr_onboarding.models import (
    HrOnboardingCase, HrOnboardingTaskInstance, HrOnboardingTaskDefinition,
    HrOnboardingMaterialRequirement, HrOnboardingMaterial, HrOnboardingAuditEvent,
    HrOnboardingActivationSnapshot,
)
from hr_onboarding.policies.completion import evaluate_completion
from hr_onboarding.policies.state_machine import assert_case_transition, validate_task_transition
from hr_onboarding.services.case_service import CaseService
from hr_onboarding.services.idempotency_service import DurableIdempotencyService, canonical_request_hash
from hr_onboarding.services.task_service import TaskService
from hr_onboarding.services.outbox_service import enqueue_outbox

DONE = {T.COMPLETED, T.WAIVED}
TERMINAL_TASKS = DONE | {T.CANCELLED}
STOPPED_CASES = {C.CANCELLED, C.DECLINED, C.PROBATION_FAILED}
ACTION_LABELS = {'assign': '分派责任人', 'start': '开始办理', 'complete': '确认完成', 'waive': '有据豁免'}


def permitted(user, code: str) -> bool:
    return bool(user and user.is_authenticated and user.is_active and
                (user.is_superuser or user.has_perm(code)))


def is_manager(user) -> bool:
    return permitted(user, 'hr05.task.manage') and permitted(user, 'hr05.case.view')


def assert_permission(user, code):
    if not permitted(user, code):
        raise PermissionDeniedError('当前账号没有此办理权限')


def clean_text(value, field, *, required=False, limit=2000):
    if not isinstance(value, str) or len(value) > limit:
        raise Hr05ApiError(f'{field} 必须为不超过 {limit} 字的文本')
    value = value.strip()
    if required and not value:
        raise Hr05ApiError(f'请填写{field}')
    return value


def expected_version(value):
    if isinstance(value, bool):
        raise Hr05ApiError('请重新读取页面后提交版本号')
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise Hr05ApiError('缺少有效版本号，请先读取最新记录')
    if str(parsed) != str(value).strip() or parsed < 1:
        raise Hr05ApiError('版本号必须为正整数')
    return parsed


def safe_case(tenant_id, case_id, *, lock=False):
    qs = HrOnboardingCase.objects.filter(tenant_id=tenant_id, pk=case_id)
    if lock:
        qs = qs.select_for_update()
    case = qs.first()
    if case is None:
        raise NotFoundError('入职单不存在或无权访问')
    return case


def with_task_context(qs):
    # One minimal identity label for an already-authorized task; never expose the
    # underlying personnel profile, contact, bank or medical record to an executor.
    from hr_onboarding.models import HrPrehireProfile
    from hr_staff.models import HrPerson
    return qs.annotate(
        assignee_username=Subquery(get_user_model().objects.filter(
            pk=OuterRef('assignee_id'), is_active=True).values('username')[:1]),
        subject_label=Coalesce(
            Subquery(HrPerson.objects.filter(tenant_id=OuterRef('tenant_id'),
                pk=OuterRef('case__hr03_person_id')).values('legal_name')[:1]),
            Subquery(HrPrehireProfile.objects.filter(tenant_id=OuterRef('tenant_id'),
                case_id=OuterRef('case_id')).values('legal_name')[:1]), Value('姓名待核对')))


def case_tasks(case, *, lock=False):
    from hr_onboarding.services.school_template_service import verify_school_template
    verify_school_template(case.template_version, case.tenant_id)
    qs = HrOnboardingTaskInstance.objects.filter(
        tenant_id=case.tenant_id, case_id=case.id, definition__tenant_id=case.tenant_id,
        definition__template_version_id=case.template_version_id,
    ).order_by('definition__sequence', 'id')
    if lock:
        qs = qs.select_for_update()
    return with_task_context(qs.select_related('definition', 'case'))


def task_projection(task, user, *, tasks=None, now=None):
    """Minimal task projection; no bank, medical, education or resume fields."""
    now = now or timezone.now()
    if tasks is None:
        tasks = list(case_tasks(task.case))
    done = {(x.cycle, x.definition.code) for x in tasks if x.status in DONE}
    missing = [code for code in task.definition.prerequisite_codes or [] if (task.cycle, code) not in done]
    automatic = task.definition.completion_type != TaskCompletionType.MANUAL
    reason = ''
    if task.case.status in STOPPED_CASES:
        reason = '入职单已终止，不能继续办理'
    elif task.status in TERMINAL_TASKS:
        reason = '该任务已结束'
    elif automatic:
        reason = '自动任务等待原系统回执，不允许手工伪造成功'
    elif task.available_at and task.available_at > now:
        reason = '尚未到可办理时间'
    elif missing:
        titles = {x.definition.code: x.definition.title for x in tasks if x.cycle == task.cycle}
        reason = '请先完成前置任务：' + '、'.join(titles.get(code, code) for code in missing)
    actions = []
    if not reason:
        current = T.READY if task.status == T.NOT_STARTED else task.status
        if task.assignee_id == user.id and permitted(user, 'hr05.task.complete'):
            if validate_task_transition(current, T.IN_PROGRESS).allowed:
                actions.append('start')
            if validate_task_transition(current, T.COMPLETED).allowed:
                actions.append('complete')
        if permitted(user, 'hr05.task.waive') and permitted(user, 'hr05.case.view'):
            if validate_task_transition(current, T.WAIVED).allowed:
                actions.append('waive')
        if not task.assignee_id:
            reason = '等待人事管理员分派责任人'
        elif task.assignee_id != user.id and not actions:
            reason = '由指定责任人办理'
    if is_manager(user) and task.status not in TERMINAL_TASKS and task.case.status not in STOPPED_CASES:
        actions.insert(0, 'assign')
    completion = task.completion_payload if isinstance(task.completion_payload, dict) else {}
    evidence = completion.get('evidence') if isinstance(completion.get('evidence'), dict) else {}
    return {
        'completion': {'note': str(completion.get('note') or completion.get('reason') or '')[:2000],
                       'evidence': str(evidence.get('reference') or '')[:1000]} if task.status in DONE else None,
        'id': str(task.id), 'case_id': str(task.case_id), 'case_no': task.case.case_no,
        'code': task.definition.code, 'title': task.definition.title,
        'subject_label': getattr(task, 'subject_label', None) or with_task_context(HrOnboardingTaskInstance.objects.filter(tenant_id=task.tenant_id, pk=task.pk)).values_list('subject_label', flat=True).first(),
        'category': task.definition.category, 'categoryLabel': task.definition.category or '入职协同',
        'responsible_role': task.assignee_type,
        'responsibleRoleLabel': str(label_for(RESPONSIBLE_ROLE_LABELS, task.assignee_type)),
        'assignee_id': task.assignee_id, 'assignee_label': (user.get_username() if task.assignee_id == user.id else getattr(task, 'assignee_username', '') or ('责任账号 #' + str(task.assignee_id) if task.assignee_id else '未分派')), 'version': task.version,
        'status': task.status, 'statusLabel': str(label_for(TASK_STATUS_LABELS, task.status)),
        'blocking_level': task.definition.blocking_level,
        'blockingLevelLabel': str(label_for(BLOCKING_LEVEL_LABELS, task.definition.blocking_level)),
        'due_at': task.due_at.isoformat() if task.due_at else None,
        'completed_at': task.completed_at.isoformat() if task.completed_at else None,
        'overdue': bool(task.due_at and task.due_at < now and task.status not in TERMINAL_TASKS),
        'is_mine': task.assignee_id == user.id,
        'actions': actions, 'blocked_reason': reason, 'missing_prerequisites': missing,
    }


def _formal_result(case):
    """Cross-check all four existing facts AND the sealed activation chain."""
    from hr_staff.models import HrPerson, HrStaffMaster, HrEmploymentRelationship, HrStaffAssignment
    from hr_onboarding.services.activation_fact_service import ActivationFactService
    t = case.tenant_id
    checks = [
        ('person', '自然人', case.hr03_person_id, HrPerson.objects.filter(tenant_id=t, pk=case.hr03_person_id)),
        ('staff', '本校教职工', case.hr03_staff_master_id,
         HrStaffMaster.objects.filter(tenant_id=t, pk=case.hr03_staff_master_id, person_id_id=case.hr03_person_id)),
        ('employment', '用工关系', case.hr03_employment_id,
         HrEmploymentRelationship.objects.filter(tenant_id=t, pk=case.hr03_employment_id, staff_id_id=case.hr03_staff_master_id)),
        ('assignment', '任职关系', case.hr03_assignment_id,
         HrStaffAssignment.objects.filter(tenant_id=t, pk=case.hr03_assignment_id, employment_relationship_id_id=case.hr03_employment_id)),
    ]
    rows = [{'key': key, 'label': label, 'id': str(pk) if pk else None, 'exists': bool(pk and qs.exists())}
            for key, label, pk, qs in checks]
    sealed = None
    snapshot = HrOnboardingActivationSnapshot.objects.filter(tenant_id=t, case_id=case.id).first()
    if snapshot:
        try:
            ActivationFactService._assert_parent_chain(snapshot)
            if snapshot.content_hash != snapshot.calculate_content_hash():
                raise VersionConflictError('正式生效凭据校验失败')
            predecessor = None
            before_payload = snapshot.canonical_payload()
            for sequence, amendment in enumerate(snapshot.amendments.order_by('sequence_no'), start=1):
                if (amendment.tenant_id != t or amendment.sequence_no != sequence
                    or amendment.predecessor_id != predecessor
                    or amendment.content_hash != amendment.calculate_content_hash()
                    or amendment.before_snapshot_json != before_payload):
                    raise VersionConflictError('正式生效更正链不完整')
                predecessor = amendment.id
                before_payload = amendment.after_snapshot_json
            fact = ActivationFactService(tenant_id=t).get_effective_fact(snapshot_id=snapshot.id)
            sealed = {'status': fact['status'], 'version': fact['version'], 'hash': fact['latest_content_hash']}
        except Hr05ApiError:
            sealed = {'status': 'INVALID'}
    valid = all(row['exists'] for row in rows) and bool(sealed and sealed.get('status') == 'EFFECTIVE')
    return {'verified': valid, 'facts': rows, 'activation': sealed}


def workflow_summary(case, user, *, lock=False):
    assert_permission(user, 'hr05.case.view')
    tasks = list(case_tasks(case, lock=lock))
    definitions = list(HrOnboardingTaskDefinition.objects.filter(
        tenant_id=case.tenant_id, template_version_id=case.template_version_id,
    ).order_by('sequence', 'code')) if case.template_version_id else []
    instantiated = {x.definition_id for x in tasks if x.cycle == 'INITIAL'}
    missing_tasks = [x.code for x in definitions if x.id not in instantiated]
    materials_qs = HrOnboardingMaterial.objects.filter(tenant_id=case.tenant_id, case_id=case.id)
    if lock:
        materials_qs = materials_qs.select_for_update()
    materials = list(materials_qs.order_by('id'))
    by_req = {x.requirement_id: x for x in materials}
    reqs = list(HrOnboardingMaterialRequirement.objects.filter(
        tenant_id=case.tenant_id, template_version_id=case.template_version_id, required=True,
        blocking_phase__in=(P.PRE_REPORT, P.REPORT, P.ACTIVATION),
    ).order_by('id')) if case.template_version_id else []
    today = timezone.localdate()
    missing_materials = [r for r in reqs if r.id not in by_req or by_req[r.id].status not in {M.VERIFIED, M.WAIVED}
                         or (by_req[r.id].status != M.WAIVED and by_req[r.id].expiry_date and by_req[r.id].expiry_date < today)]
    formal = _formal_result(case)
    result = evaluate_completion(case_status=case.status,
        blocking_tasks=[(x.definition.blocking_level, x.status in DONE) for x in tasks],
        open_risks=[RiskCode.MISSING_BLOCKING_DOCUMENT] if missing_materials else [])
    blockers = []
    if case.status not in {C.ACTIVE, C.ONBOARDING_IN_PROGRESS, C.ONBOARDING_COMPLETED}:
        blockers.append({'code': 'CASE_STAGE', 'label': '当前办理阶段不允许此结案动作；需核对正式生效与试用的既有流程，不在此回退试用状态', 'url': f'/hr/onboarding/prehires/{case.id}'})
    if not formal['verified']:
        blockers.append({'code': 'FORMAL_FACTS', 'label': '四层人员事实或正式生效凭据尚未核对通过', 'url': f'/hr/onboarding/prehires/{case.id}'})
    if not case.template_version_id:
        blockers.append({'code': 'TEMPLATE_UNSET', 'label': '尚未绑定入职模板，无法判定协同任务是否齐全', 'url': ''})
    if case.template_version_id and case.template_version.tenant_id != case.tenant_id:
        blockers.append({'code': 'TEMPLATE_SCOPE', 'label': '模板学校归属异常，请先核对', 'url': ''})
    if HrOnboardingTaskInstance.objects.filter(case_id=case.id).count() != len(tasks):
        blockers.append({'code': 'TASK_SCOPE', 'label': '存在学校或模板归属不一致的任务，不能结案', 'url': ''})
    if missing_tasks:
        blockers.append({'code': 'TASKS_MISSING', 'label': '模板任务尚未完整生成：' + '、'.join(missing_tasks), 'url': ''})
    if missing_materials:
        blockers.append({'code': 'MATERIALS', 'label': '必需材料未完成核验或已过期：' + '、'.join(x.label for x in missing_materials),
                         'url': f'/hr/onboarding/materials?case_id={case.id}'})
    if case.data_conflicts.filter(tenant_id=case.tenant_id, resolution='OPEN').exists():
        blockers.append({'code': 'DATA_CONFLICT', 'label': '仍有未解决的人员资料冲突', 'url': f'/hr/onboarding/prehires/{case.id}'})
    for item in tasks:
        if item.definition.blocking_level == B.BLOCKS_ONBOARDING_COMPLETE and item.status not in DONE:
            blockers.append({'code': 'TASK', 'task_id': str(item.id), 'label': item.definition.title, 'url': ''})
    audit_rows = list(HrOnboardingAuditEvent.objects.filter(tenant_id=case.tenant_id, case_id=case.id).annotate(
        actor_label=Subquery(get_user_model().objects.filter(pk=OuterRef('actor_user_id')).values('username')[:1]))
                      .order_by('-occurred_at', '-id')[:15])
    signature = canonical_request_hash({
        'case': [str(case.id), case.version, case.status, str(case.template_version_id)],
        'tasks': [[str(x.id), x.version, x.status, x.assignee_id, x.definition.blocking_level] for x in tasks],
        'definitions': [[str(d.id), d.code, d.blocking_level, d.prerequisite_codes] for d in definitions],
        'materials': [[str(m.id), m.status, m.updated_at.isoformat()] for m in materials],
        'requirements': [[str(r.id), r.required, r.blocking_phase] for r in reqs],
        'formal': formal, 'blockers': blockers,
    })
    outstanding = [x for x in tasks if x.status not in TERMINAL_TASKS]
    return {
        'case': {'id': str(case.id), 'case_no': case.case_no, 'status': case.status,
                 'statusLabel': str(label_for(CASE_STATUS_LABELS, case.status)), 'version': case.version},
        'fingerprint': signature,
        'can_complete': bool(result.eligible and not blockers and is_manager(user) and permitted(user, 'hr05.case.activate')),
        'can_initialize': bool(missing_tasks and is_manager(user) and case.status not in STOPPED_CASES),
        'formal_result': formal, 'blockers': blockers, 'missing_tasks': missing_tasks,
        'summary': {'total': len(tasks), 'completed': sum(x.status in DONE for x in tasks),
                    'outstanding': len(outstanding), 'unassigned': sum(not x.assignee_id for x in outstanding),
                    'payroll_blockers': sum(x.definition.blocking_level == B.BLOCKS_PAYROLL for x in outstanding)},
        'tasks': [task_projection(x, user, tasks=tasks) for x in tasks],
        'history': [{'id': str(x.id), 'action': x.action, 'actor_user_id': x.actor_user_id, 'actor_label': x.actor_label or ('账号 #' + str(x.actor_user_id)),
                     'occurred_at': x.occurred_at.isoformat(), 'business_id': x.business_id} for x in audit_rows],
        'next_links': [{'label': '核对正式人员与任职', 'url': f'/hr/staff/{case.hr03_staff_master_id}/'}]
            if formal['verified'] and permitted(user, 'hr05.case.view') else [],
    }


class OnboardingWorkflowService:
    def __init__(self, *, tenant_id, user, request_id=''):
        self.tenant_id = tenant_id
        self.user = user
        self.request_id = str(request_id)[:64]
        if not tenant_id or not user or not user.is_authenticated or not user.is_active:
            raise PermissionDeniedError('请选择有权访问的学校并登录')

    def _audit(self, case, action, business_id, before, after, reason=''):
        event = HrOnboardingAuditEvent.objects.create(
            tenant_id=self.tenant_id, case_id=case.id, actor_user_id=self.user.id,
            action=action, business_type='ONBOARDING_WORKFLOW', business_id=str(business_id),
            before_snapshot_ref=str(before), after_snapshot_ref=str(after),
            reason=reason, request_id=self.request_id,
        )
        return {'id': str(event.id), 'action': action, 'case_id': str(case.id),
                'business_id': str(business_id), 'actor_user_id': self.user.id,
                'occurred_at': event.occurred_at.isoformat(), 'version': after}

    @transaction.atomic
    def task_command(self, *, task_id, action, version, idempotency_key, data):
        version = expected_version(version)
        perm = {'assign': 'hr05.task.manage', 'start': 'hr05.task.complete',
                'complete': 'hr05.task.complete', 'waive': 'hr05.task.waive'}.get(action)
        if not perm:
            raise Hr05ApiError('不支持的任务动作')
        assert_permission(self.user, perm)
        task_ref = HrOnboardingTaskInstance.objects.filter(tenant_id=self.tenant_id, pk=task_id).values('case_id').first()
        if task_ref is None:
            raise NotFoundError('任务不存在或无权访问')
        case = safe_case(self.tenant_id, task_ref['case_id'], lock=True)
        task = case_tasks(case, lock=True).filter(id=task_id).first()
        if task is None:
            raise NotFoundError('任务所属模板或学校不一致')
        if action == 'assign' and not is_manager(self.user):
            raise PermissionDeniedError('分派任务需要入职管理权限')
        if action in {'start', 'complete'} and task.assignee_id != self.user.id:
            raise PermissionDeniedError('仅指定责任人可办理，请先由人事管理员分派')
        if action == 'waive':
            assert_permission(self.user, 'hr05.case.view')
        idem = DurableIdempotencyService(tenant_id=self.tenant_id, operation='workflow.task.' + action)
        claim = idem.claim(idempotency_key=idempotency_key, request_payload={
            'actor': self.user.id, 'task': str(task_id), 'version': version, 'data': data,
        })
        if claim.is_replay:
            return {'receipt': claim.record.response_summary, 'replayed': True,
                    'task': task_projection(task, self.user)}
        if case.status in STOPPED_CASES or task.status in TERMINAL_TASKS:
            raise InvalidStateTransitionError('入职单或任务已结束，请查看最新记录')
        if task.version != version:
            raise VersionConflictError('任务已由他人更新，请读取最新记录后再办理')
        before = task.version
        note = clean_text(data.get('note', ''), '办理说明')
        if action == 'assign':
            username = clean_text(data.get('username', ''), '责任人登录账号', required=True, limit=150)
            target = get_user_model().objects.filter(username=username, is_active=True).first()
            if target is None or not permitted(target, 'hr05.task.complete'):
                raise PermissionDeniedError('责任人账号不可用或没有任务办理权限')
            from base.auth_backends import get_allowed_company_ids
            if self.tenant_id not in (get_allowed_company_ids(target) or ()):
                raise PermissionDeniedError('责任人不属于当前学校')
            if task.assignee_id and task.assignee_id != target.id and not note:
                raise Hr05ApiError('转派任务必须填写原因')
            task.assignee_id = target.id
            task.version += 1
            task.save(update_fields=['assignee_id', 'version', 'updated_at'])
        else:
            projection = task_projection(task, self.user)
            if action not in projection['actions']:
                raise TaskPrerequisiteNotMetError(projection['blocked_reason'] or '当前阶段不支持此动作')
            service = TaskService(tenant_id=self.tenant_id, actor_user_id=self.user.id)
            if action == 'start':
                task = service.start_task(task)
            elif action == 'complete':
                note = clean_text(data.get('note', ''), '完成说明', required=True)
                evidence = clean_text(data.get('evidence', ''), '办理依据或凭证编号', required=True, limit=1000)
                task = service.complete_task(task, note=note, evidence={'reference': evidence})
            else:
                note = clean_text(data.get('reason', ''), '豁免依据', required=True)
                task = service.waive_task(task, reason=note)
        receipt = self._audit(case, 'TASK_' + action.upper(), task.id, before, task.version, note)
        receipt.update({'status': task.status, 'assignee_id': task.assignee_id})
        idem.succeed(claim.record, authority_type='HrOnboardingTaskInstance', authority_id=task.id, response_summary=receipt)
        return {'receipt': receipt, 'replayed': False, 'task': task_projection(task, self.user)}

    @transaction.atomic
    def case_command(self, *, case_id, action, version, idempotency_key, fingerprint=''):
        if not is_manager(self.user):
            raise PermissionDeniedError('需要入职单查看和任务管理权限')
        if action == 'complete':
            assert_permission(self.user, 'hr05.case.activate')
        elif action != 'initialize':
            raise Hr05ApiError('不支持的入职动作')
        version = expected_version(version)
        case = safe_case(self.tenant_id, case_id, lock=True)
        idem = DurableIdempotencyService(tenant_id=self.tenant_id, operation='workflow.case.' + action)
        claim = idem.claim(idempotency_key=idempotency_key, request_payload={
            'actor': self.user.id, 'case': str(case_id), 'version': version, 'fingerprint': fingerprint,
        })
        if claim.is_replay:
            return {'receipt': claim.record.response_summary, 'replayed': True, 'case_status': case.status}
        if case.version != version:
            raise VersionConflictError('入职单已更新，请重新核对')
        if case.status in STOPPED_CASES:
            raise InvalidStateTransitionError('入职单已终止')
        before = case.version
        if action == 'initialize':
            if not case.template_version_id or case.template_version.tenant_id != self.tenant_id:
                raise Hr05ApiError('请先为此入职单绑定有效的本校模板')
            created = TaskService(tenant_id=self.tenant_id, actor_user_id=self.user.id).instantiate_tasks(case)
            case.version += 1
            case.save(update_fields=['version', 'updated_at'])
            receipt = self._audit(case, 'TASKS_INITIALIZED', case.id, before, case.version)
            receipt['created_tasks'] = created
        else:
            current = workflow_summary(case, self.user, lock=True)
            if not fingerprint or fingerprint != current['fingerprint']:
                raise VersionConflictError('任务、材料或正式记录已改变，请重新核对办理结果')
            if not current['can_complete']:
                raise Hr05ApiError('尚不能结案，请先处理阻塞项', details={'blockers': current['blockers']})
            service = CaseService(tenant_id=self.tenant_id, actor_user_id=self.user.id)
            if case.status == C.ACTIVE:
                assert_case_transition(case.status, C.ONBOARDING_IN_PROGRESS)
                service._transition_locked(case, C.ONBOARDING_IN_PROGRESS, 'BEGIN_COLLABORATION', '协同结果已核对')
            assert_case_transition(case.status, C.ONBOARDING_COMPLETED)
            service._transition_locked(case, C.ONBOARDING_COMPLETED, 'COMPLETE_COLLABORATION', '按原协同完成规则核验通过')
            receipt = self._audit(case, 'ONBOARDING_COMPLETED', case.id, before, case.version)
            receipt.update({'status': case.status, 'checked_fingerprint': fingerprint,
                            'remaining_tasks': current['summary']['outstanding']})
            enqueue_outbox(tenant_id=self.tenant_id, event_type='OnboardingCompleted',
                           aggregate_type='HrOnboardingCase', aggregate_id=str(case.id),
                           correlation_id=self.request_id,
                           payload={'case_id': str(case.id), 'staff_master_id': str(case.hr03_staff_master_id),
                                    'version': case.version, 'receipt_id': receipt['id']})
        idem.succeed(claim.record, authority_type='HrOnboardingCase', authority_id=case.id, response_summary=receipt)
        return {'receipt': receipt, 'replayed': False, 'case_status': case.status}


def task_inbox(*, tenant_id, user, keyword='', state='open', page=1, page_size=20, case_id=None):
    if not any(permitted(user, p) for p in ('hr05.task.manage', 'hr05.task.complete', 'hr05.task.waive')):
        raise PermissionDeniedError('没有任务工作台访问权限')
    qs = HrOnboardingTaskInstance.objects.filter(
        tenant_id=tenant_id, case__tenant_id=tenant_id, definition__tenant_id=tenant_id,
        definition__template_version_id=F('case__template_version_id'),
    ).exclude(case__status__in=STOPPED_CASES)
    if state not in {'open', 'mine', 'unassigned', 'overdue', 'done'}:
        raise Hr05ApiError('不支持的任务筛选状态')
    if state == 'unassigned' and not is_manager(user):
        raise PermissionDeniedError('只有人事管理员可查看待分派队列')
    if case_id:
        from uuid import UUID
        try:
            case_id = UUID(str(case_id))
        except (ValueError, TypeError):
            raise Hr05ApiError('入职单标识无效')
        qs = qs.filter(case_id=case_id)
    if not is_manager(user):
        qs = qs.filter(assignee_id=user.id)
    elif state == 'mine':
        qs = qs.filter(assignee_id=user.id)
    elif state == 'unassigned':
        qs = qs.filter(assignee_id__isnull=True)
    if state == 'done':
        qs = qs.filter(status__in=DONE)
    else:
        qs = qs.exclude(status__in=TERMINAL_TASKS)
    if state == 'overdue':
        qs = qs.filter(due_at__lt=timezone.now())
    if keyword:
        qs = qs.filter(Q(case__case_no__icontains=keyword) | Q(definition__title__icontains=keyword))
    qs = with_task_context(qs).annotate(_priority=Case(When(definition__blocking_level=B.BLOCKS_ONBOARDING_COMPLETE, then=Value(0)),
        default=Value(1), output_field=IntegerField())).select_related('case', 'definition').order_by('_priority', 'due_at', 'id')
    pager = Paginator(qs, max(1, min(100, page_size)))
    selected = pager.get_page(max(1, page))
    rows = list(selected)
    # One dependency query per page, not per task. Access checks precede projections.
    siblings = list(HrOnboardingTaskInstance.objects.filter(
        tenant_id=tenant_id, case_id__in={x.case_id for x in rows}, definition__tenant_id=tenant_id,
        definition__template_version_id=F('case__template_version_id'),
    ).select_related('definition'))
    grouped = {}
    for row in siblings:
        grouped.setdefault(row.case_id, []).append(row)
    now = timezone.now()
    return {'items': [task_projection(x, user, tasks=grouped.get(x.case_id, []), now=now) for x in rows],
            'total': pager.count, 'page': selected.number, 'hasNext': selected.has_next(),
            'pageSize': pager.per_page, 'is_manager': is_manager(user),
            'can_view_cases': permitted(user, 'hr05.case.view')}


def find_assignees(*, tenant_id, user, keyword):
    """Bounded, school-scoped work-account picker; never a general directory."""
    if not is_manager(user):
        raise PermissionDeniedError('仅入职任务管理员可查找责任账号')
    term = clean_text(keyword, '账号或姓名关键词', required=True, limit=150)
    if len(term) < 2:
        raise Hr05ApiError('请输入至少两个字符缩小查找范围')
    from base.auth_backends import get_allowed_company_ids
    candidates = list(get_user_model().objects.filter(is_active=True).filter(
        Q(username__icontains=term) | Q(first_name__icontains=term) | Q(last_name__icontains=term)
    ).order_by('username', 'id')[:51])
    items = []
    for person in candidates[:50]:
        if permitted(person, 'hr05.task.complete') and tenant_id in (get_allowed_company_ids(person) or ()):
            items.append({'username': person.get_username(), 'label': person.get_full_name().strip() or person.get_username()})
            if len(items) > 20:
                break
    return {'items': items[:20], 'limited': len(candidates) > 50 or len(items) > 20,
            'hint': '只显示本校已有任务办理权限的有效账号；选择不会增加其权限。'}
