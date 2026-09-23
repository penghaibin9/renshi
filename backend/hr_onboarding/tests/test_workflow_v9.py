"""Actual ORM workflow tests. Permission sets/membership are explicit test doubles;
this suite does not certify the production company RBAC backend or bank links.
"""
from datetime import date, timedelta
import json
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.test import TestCase, RequestFactory, override_settings
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from hr_onboarding.api import workflow
from hr_onboarding.api.exceptions import Hr05ApiError, PermissionDeniedError, VersionConflictError, IdempotencyConflictError
from hr_onboarding.constants import TaskStatus as T, CaseStatus as C
from hr_onboarding.models import (
    HrOnboardingCase, HrOnboardingTemplate, HrOnboardingTemplateVersion,
    HrOnboardingTaskDefinition, HrOnboardingTaskInstance, HrOnboardingAuditEvent,
    HrOnboardingActivationSnapshot, HrOnboardingMaterialRequirement, HrOnboardingMaterial,
    HrOnboardingStageTransition, HrOnboardingIdempotencyRecord, HrPrehireProfile,
    HrOnboardingOutboxEvent,
)
from hr_onboarding.services.workflow_service import OnboardingWorkflowService, workflow_summary, task_inbox
from hr_onboarding.services.task_service import TaskService
from hr_onboarding.api.selectors import list_cases
from hr_staff.models import HrPerson, HrStaffMaster, HrEmploymentRelationship, HrStaffAssignment


def actor(name, perms=(), superuser=False):
    user = get_user_model().objects.create_user(username=name, password='test-only-not-production', is_superuser=superuser)
    user.has_perm = lambda code, obj=None: superuser or code in perms
    return user


def case_fixture(tenant=1, number='1001', formal=True):
    tpl = HrOnboardingTemplate.objects.create(tenant_id=tenant, code='TPL'+number, name='本校入职程序')
    ver = HrOnboardingTemplateVersion.objects.create(tenant_id=tenant, template=tpl, version_no=1, status='ACTIVE')
    case = HrOnboardingCase.objects.create(tenant_id=tenant, case_no=number,
        source_type='LEGAL_MANUAL_MIGRATION', source_id=number, template_version=ver,
        status=C.ACTIVE if formal else C.PREPARING)
    HrPrehireProfile.objects.create(tenant_id=tenant, case=case, legal_name='测试老师'+number)
    if formal:
        person = HrPerson.objects.create(tenant_id=tenant, legal_name='测试老师'+number)
        staff = HrStaffMaster.objects.create(tenant_id=tenant, person_id=person, staff_no='G'+number)
        rel = HrEmploymentRelationship.objects.create(tenant_id=tenant, staff_id=staff, effective_from=date(2026, 1, 1))
        assign = HrStaffAssignment.objects.create(tenant_id=tenant, employment_relationship_id=rel, effective_from=date(2026, 1, 1))
        case.hr03_person_id = person.id; case.hr03_staff_master_id = staff.id
        case.hr03_employment_id = rel.id; case.hr03_assignment_id = assign.id
        case.save()
        HrOnboardingActivationSnapshot.objects.create(tenant_id=tenant, case=case,
            person_id=person.id, staff_master_id=staff.id, employment_id=rel.id, assignment_id=assign.id)
    return case


def definition(case, code='MAIL', **kwargs):
    return HrOnboardingTaskDefinition.objects.create(tenant_id=case.tenant_id,
        template_version=case.template_version, code=code, title='办理'+code,
        blocking_level=kwargs.pop('blocking_level', 'BLOCKS_ONBOARDING_COMPLETE'), **kwargs)


class WorkflowV9Tests(TestCase):
    def setUp(self):
        self.manager = actor('hr-manager', superuser=True)
        self.worker = actor('it-worker', ['hr05.task.complete'])
        self.other = actor('other-worker', ['hr05.task.complete'])
        self.case = case_fixture()
        self.definition = definition(self.case)
        self.task = HrOnboardingTaskInstance.objects.create(tenant_id=1, case=self.case,
            definition=self.definition, assignee_id=self.worker.id)

    def service(self, user=None, tenant=1):
        return OnboardingWorkflowService(tenant_id=tenant, user=user or self.manager, request_id='v9-test')

    def command(self, action, user=None, data=None, key=None, version=None):
        self.task.refresh_from_db()
        return self.service(user or self.worker).task_command(task_id=self.task.id, action=action,
            data=data or {}, version=version or self.task.version, idempotency_key=key or uuid4().hex)

    def finish_task(self):
        self.command('start')
        return self.command('complete', data={'note':'已按申请办理', 'evidence':'TEST-TICKET-001'})

    def test_start_complete_produce_actual_state_receipts_and_audit(self):
        self.finish_task(); self.task.refresh_from_db()
        self.assertEqual(self.task.status, T.COMPLETED)
        self.assertEqual(self.task.completion_payload['completed_by'], self.worker.id)
        self.assertEqual(HrOnboardingAuditEvent.objects.count(), 2)
        self.assertEqual(HrOnboardingIdempotencyRecord.objects.count(), 2)

    def test_old_assignee_or_random_user_cannot_complete(self):
        with self.assertRaises(PermissionDeniedError): self.command('start', user=self.other)
        self.assertEqual(HrOnboardingAuditEvent.objects.count(), 0)

    def test_even_manager_must_be_assigned_for_manual_completion(self):
        with self.assertRaises(PermissionDeniedError): self.command('start', user=self.manager)

    def test_missing_evidence_is_not_completed(self):
        self.command('start')
        with self.assertRaises(Hr05ApiError): self.command('complete', data={'note':'办好了'})
        self.task.refresh_from_db(); self.assertEqual(self.task.status, T.IN_PROGRESS)

    def test_stale_version_does_not_write(self):
        self.command('start')
        with self.assertRaises(VersionConflictError): self.command('complete', version=1, data={'note':'a','evidence':'b'})
        self.assertEqual(HrOnboardingAuditEvent.objects.count(),1)

    def test_lost_response_retry_replays_once_with_original_version(self):
        first=self.command('start',key='repeat',version=1)
        replay=self.command('start',key='repeat',version=1)
        self.assertTrue(replay['replayed']); self.assertEqual(first['receipt'],replay['receipt'])
        self.assertEqual(HrOnboardingAuditEvent.objects.count(),1)

    def test_same_key_different_payload_rejected(self):
        self.command('start',key='repeat',version=1)
        with self.assertRaises(IdempotencyConflictError):
            self.command('start',key='repeat',version=1,data={'note':'different'})

    def test_audit_failure_rolls_back_task_and_idempotency(self):
        with patch.object(HrOnboardingAuditEvent.objects, 'create', side_effect=RuntimeError('storage failure')):
            with self.assertRaises(RuntimeError): self.command('start')
        self.task.refresh_from_db(); self.assertEqual(self.task.status,T.NOT_STARTED)
        self.assertEqual(HrOnboardingIdempotencyRecord.objects.count(),0)

    def test_prerequisite_blocks_start(self):
        self.definition.prerequisite_codes=['IDENTITY']; self.definition.save()
        with self.assertRaises(Hr05ApiError): self.command('start')

    def test_future_availability_blocks_start(self):
        self.task.available_at=timezone.now()+timedelta(days=1); self.task.save()
        with self.assertRaises(Hr05ApiError): self.command('start')

    def test_automated_task_does_not_accept_manual_success(self):
        self.definition.completion_type='AUTOMATED'; self.definition.save()
        with self.assertRaises(Hr05ApiError): self.command('start')

    def test_cancelled_case_blocks_execution(self):
        self.case.status=C.CANCELLED; self.case.save()
        with self.assertRaises(Hr05ApiError): self.command('start')

    def test_assign_checks_real_username_permission_and_membership(self):
        # User fetched during assignment; attach explicit permission for this test.
        User=get_user_model()
        with patch.object(User,'has_perm',return_value=True), patch('base.auth_backends.get_allowed_company_ids',return_value={1}):
            result=self.command('assign',user=self.manager,data={'username':self.other.username,'note':'轮岗交接'})
        self.assertEqual(result['task']['assignee_id'],self.other.id)
        with self.assertRaises(PermissionDeniedError): self.command('start',user=self.worker)

    def test_assign_foreign_school_rejected(self):
        User=get_user_model()
        with patch.object(User,'has_perm',return_value=True), patch('base.auth_backends.get_allowed_company_ids',return_value={2}):
            with self.assertRaises(PermissionDeniedError):
                self.command('assign',user=self.manager,data={'username':self.other.username,'note':'转派'})

    def test_task_only_worker_sees_only_own_minimal_inbox(self):
        other_def=definition(self.case,'CARD')
        HrOnboardingTaskInstance.objects.create(tenant_id=1,case=self.case,definition=other_def,assignee_id=self.other.id)
        response=task_inbox(tenant_id=1,user=self.worker)
        self.assertEqual(response['total'],1)
        self.assertNotIn('bank',json.dumps(response));self.assertNotIn('legal_name',json.dumps(response))
        self.assertEqual(response['items'][0]['subject_label'], '测试老师1001')
        self.assertNotIn('primary_email',json.dumps(response))
        with self.assertRaises(PermissionDeniedError): workflow_summary(self.case,self.worker)

    def test_foreign_task_id_never_resolves(self):
        with self.assertRaises(Hr05ApiError):
            self.service(self.manager,2).task_command(task_id=self.task.id,action='start',version=1,idempotency_key='x',data={})

    def test_no_task_instances_is_not_fake_100_percent(self):
        self.task.delete(); report=workflow_summary(self.case,self.manager)
        self.assertIn('MAIL',report['missing_tasks']);self.assertFalse(report['can_complete'])
        self.assertEqual(HrOnboardingTaskInstance.objects.count(),0)

    def test_initialize_only_missing_tasks_then_replay(self):
        definition(self.case,'CARD')
        r=self.service().case_command(case_id=self.case.id,action='initialize',version=self.case.version,idempotency_key='init')
        self.assertEqual(r['receipt']['created_tasks'],1)
        rr=self.service().case_command(case_id=self.case.id,action='initialize',version=self.case.version,idempotency_key='init')
        self.assertTrue(rr['replayed']); self.assertEqual(HrOnboardingTaskInstance.objects.count(),2)

    def test_summary_is_readonly(self):
        before=(self.case.version,self.task.version,HrOnboardingAuditEvent.objects.count())
        workflow_summary(self.case,self.manager)
        self.case.refresh_from_db();self.task.refresh_from_db()
        self.assertEqual(before,(self.case.version,self.task.version,HrOnboardingAuditEvent.objects.count()))

    def test_incomplete_required_tasks_block_case_completion(self):
        summary=workflow_summary(self.case,self.manager)
        self.assertFalse(summary['can_complete'])
        with self.assertRaises(Hr05ApiError): self.service().case_command(case_id=self.case.id,action='complete',version=1,idempotency_key='close',fingerprint=summary['fingerprint'])

    def test_actual_four_facts_verified_before_case_completion(self):
        self.finish_task()
        self.case.hr03_assignment_id=uuid4(); self.case.save()
        summary=workflow_summary(self.case,self.manager)
        self.assertFalse(summary['formal_result']['verified']); self.assertFalse(summary['can_complete'])

    def test_missing_required_material_blocks_case_completion(self):
        self.finish_task()
        HrOnboardingMaterialRequirement.objects.create(tenant_id=1,template_version=self.case.template_version,
            material_type='ID',label='身份原件',required=True,blocking_phase='ACTIVATION')
        summary=workflow_summary(self.case,self.manager)
        self.assertTrue(any(x['code']=='MATERIALS' for x in summary['blockers']))

    def test_expired_verified_material_is_not_counted_as_clear(self):
        self.finish_task()
        req=HrOnboardingMaterialRequirement.objects.create(tenant_id=1,template_version=self.case.template_version,
            material_type='ID',label='有效材料',required=True,blocking_phase='ACTIVATION')
        HrOnboardingMaterial.objects.create(tenant_id=1,case=self.case,requirement=req,status='VERIFIED',expiry_date=date(2020,1,1))
        self.assertFalse(workflow_summary(self.case,self.manager)['can_complete'])

    def test_successful_completion_uses_existing_state_edges_and_outbox(self):
        self.finish_task(); summary=workflow_summary(self.case,self.manager)
        self.assertTrue(summary['can_complete'])
        result=self.service().case_command(case_id=self.case.id,action='complete',version=1,idempotency_key='close',fingerprint=summary['fingerprint'])
        self.case.refresh_from_db();self.assertEqual(self.case.status,C.ONBOARDING_COMPLETED)
        self.assertEqual(HrOnboardingStageTransition.objects.count(),2)
        self.assertEqual(HrOnboardingOutboxEvent.objects.filter(event_type='OnboardingCompleted').count(),1)
        replay=self.service().case_command(case_id=self.case.id,action='complete',version=1,idempotency_key='close',fingerprint=summary['fingerprint'])
        self.assertEqual(replay['receipt'],result['receipt']);self.assertEqual(HrOnboardingStageTransition.objects.count(),2)

    def test_nonblocking_task_remains_real_after_case_completion(self):
        self.finish_task()
        extra=definition(self.case,'TRAINING',blocking_level='NON_BLOCKING')
        HrOnboardingTaskInstance.objects.create(tenant_id=1,case=self.case,definition=extra,assignee_id=self.worker.id)
        summary=workflow_summary(self.case,self.manager);self.assertTrue(summary['can_complete'])
        self.assertEqual(summary['summary']['outstanding'],1)
        result=self.service().case_command(case_id=self.case.id,action='complete',version=1,idempotency_key='close',fingerprint=summary['fingerprint'])
        self.assertEqual(result['receipt']['remaining_tasks'],1)

    def test_child_change_rejects_stale_completion_digest(self):
        self.finish_task(); summary=workflow_summary(self.case,self.manager)
        definition(self.case,'NEW-REQUIREMENT')
        with self.assertRaises(VersionConflictError): self.service().case_command(case_id=self.case.id,action='complete',version=1,idempotency_key='close',fingerprint=summary['fingerprint'])

    def test_completion_outbox_failure_rolls_back_state(self):
        self.finish_task();summary=workflow_summary(self.case,self.manager)
        with patch('hr_onboarding.services.workflow_service.enqueue_outbox',side_effect=RuntimeError('outbox')):
            with self.assertRaises(RuntimeError): self.service().case_command(case_id=self.case.id,action='complete',version=1,idempotency_key='close',fingerprint=summary['fingerprint'])
        self.case.refresh_from_db();self.assertEqual(self.case.status,C.ACTIVE)
        self.assertEqual(HrOnboardingStageTransition.objects.count(),0)

    def test_case_search_name_number_and_tenant_scope(self):
        case_fixture(2,'2002')
        self.assertEqual(list_cases(tenant_id=1,keyword='测试老师1001')['total'],1)
        self.assertEqual(list_cases(tenant_id=1,keyword='G1001')['total'],1)
        self.assertEqual(list_cases(tenant_id=1,keyword='测试老师2002')['total'],0)

    def test_search_query_count_does_not_scale_per_person(self):
        for i in range(12): case_fixture(1,str(3000+i),formal=False)
        with CaptureQueriesContext(connection) as queries:
            result=list_cases(tenant_id=1,page_size=100)
        self.assertEqual(len(result['items']),13);self.assertLessEqual(len(queries),3)

    def test_cross_tenant_dirty_profile_name_not_exposed(self):
        HrPrehireProfile.objects.filter(case=self.case).update(tenant_id=2,legal_name='SECRET-NAME')
        self.case.hr03_person_id=None;self.case.save()
        result=list_cases(tenant_id=1)
        self.assertNotIn('SECRET-NAME',json.dumps(result))

    def test_canonical_post_requires_if_match_and_idempotency(self):
        from hr_onboarding.api.tasks import task_start
        request=RequestFactory().post('/tasks/x/start',{},content_type='application/json')
        request.user=self.worker
        with patch('hr_onboarding.api.base.resolve_tenant_from_request',return_value=1),patch('base.auth_backends.get_allowed_company_ids',return_value={1}):
            response=task_start(request,self.task.id)
        self.assertEqual(response.status_code,400)
        self.task.refresh_from_db();self.assertEqual(self.task.status,T.NOT_STARTED)

    def test_post_rejects_client_actor_or_status(self):
        request=RequestFactory().post('/x',{'version':1,'actor':999,'status':'COMPLETED'},content_type='application/json')
        with self.assertRaises(Hr05ApiError): workflow.command_data(request)

    def test_post_get_method_not_allowed(self):
        request=RequestFactory().get('/x');request.user=self.manager
        self.assertEqual(workflow.complete(request,self.case.id).status_code,405)

    def test_inbox_pagination_is_stable(self):
        for i in range(7):
            HrOnboardingTaskInstance.objects.create(tenant_id=1,case=self.case,definition=definition(self.case,'T'+str(i)),assignee_id=self.worker.id)
        first=task_inbox(tenant_id=1,user=self.worker,page=1,page_size=3)
        second=task_inbox(tenant_id=1,user=self.worker,page=2,page_size=3)
        self.assertEqual(first['total'],8);self.assertTrue(first['hasNext'])
        self.assertFalse({x['id'] for x in first['items']} & {x['id'] for x in second['items']})

class PersonalTodoV9Tests(TestCase):
    def test_unassigned_tasks_are_not_each_users_personal_todo(self):
        from hr_onboarding.providers.todo import OnboardingTaskTodoProvider
        from hr_control_center.context import HrRequestContext
        case=case_fixture();d=definition(case)
        assigned=HrOnboardingTaskInstance.objects.create(tenant_id=1,case=case,definition=d,assignee_id=42)
        HrOnboardingTaskInstance.objects.create(tenant_id=1,case=case,definition=d,cycle='EXTRA',assignee_id=None)
        context=HrRequestContext(tenant_id=1,user_id=42)
        result=OnboardingTaskTodoProvider().list_todos(context)
        self.assertEqual(result['total'],1);self.assertIn(str(assigned.id),result['items'][0]['action_url'])

    def test_task_executor_is_allowed_without_case_manager_permission(self):
        from hr_control_center.services.todo_service import TodoService
        from hr_onboarding.providers.todo import OnboardingTaskTodoProvider
        user=actor('task-only',['hr05.task.complete'])
        self.assertTrue(TodoService._allowed(OnboardingTaskTodoProvider(),user))
        self.assertFalse(TodoService._allowed(OnboardingTaskTodoProvider(),actor('no-permission')))

    def test_stopped_case_is_not_still_a_personal_todo(self):
        from hr_onboarding.providers.todo import OnboardingTaskTodoProvider
        from hr_control_center.context import HrRequestContext
        case=case_fixture();case.status='CANCELLED';case.save();d=definition(case)
        HrOnboardingTaskInstance.objects.create(tenant_id=1,case=case,definition=d,assignee_id=42)
        self.assertEqual(OnboardingTaskTodoProvider().get_summary(HrRequestContext(tenant_id=1,user_id=42)).total,0)

class AssigneePickerV9Tests(TestCase):
    def test_picker_filters_school_permission_and_disabled_accounts(self):
        from hr_onboarding.services.workflow_service import find_assignees
        User=get_user_model();manager=actor('manager-picker',superuser=True)
        good=actor('test-worker');foreign=actor('test-foreign');no_perm=actor('test-reader');disabled=actor('test-disabled');disabled.is_active=False;disabled.save()
        with patch.object(User,'has_perm',lambda u,p: u.pk in {good.pk,foreign.pk}), patch('base.auth_backends.get_allowed_company_ids',side_effect=lambda u:{1} if u.pk==good.pk else {2}):
            result=find_assignees(tenant_id=1,user=manager,keyword='test')
        self.assertEqual([x['username'] for x in result['items']],['test-worker'])
        self.assertEqual(set(result['items'][0]),{'username','label'})

    def test_task_only_executor_cannot_search_general_accounts(self):
        from hr_onboarding.services.workflow_service import find_assignees
        with self.assertRaises(PermissionDeniedError):find_assignees(tenant_id=1,user=actor('worker-picker',['hr05.task.complete']),keyword='test')

    def test_empty_or_oversized_search_is_rejected(self):
        from hr_onboarding.services.workflow_service import find_assignees
        manager=actor('manager-picker',superuser=True)
        for term in ['', 'a', 'a'*151]:
            with self.assertRaises(Hr05ApiError):find_assignees(tenant_id=1,user=manager,keyword=term)


    def test_platform_account_without_school_membership_is_not_dispatch_target(self):
        from hr_onboarding.services.workflow_service import find_assignees
        manager=actor('manager-platform',superuser=True);platform=actor('platform-account',superuser=True)
        case=case_fixture(number='platform-check');d=definition(case)
        task=HrOnboardingTaskInstance.objects.create(tenant_id=1,case=case,definition=d)
        with patch('base.auth_backends.get_allowed_company_ids',return_value=set()):
            self.assertEqual(find_assignees(tenant_id=1,user=manager,keyword='platform-account')['items'],[])
            with self.assertRaises(PermissionDeniedError):
                OnboardingWorkflowService(tenant_id=1,user=manager).task_command(task_id=task.id,
                    action='assign',version=1,idempotency_key='platform-assign',data={'username':platform.username})
