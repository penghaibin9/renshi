"""School-template contract tests on ORM and real Django permissions.

Company membership is patched ONLY in HTTP tests, explicitly not a production
SSO/company-scope certificate. Service tests never claim that boundary.
"""
import copy
import json
from datetime import date
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase, SimpleTestCase, Client, override_settings

from hr_onboarding.api.exceptions import Hr05ApiError, PermissionDeniedError, VersionConflictError, IdempotencyConflictError
from hr_onboarding.models import (HrOnboardingTemplate, HrOnboardingTemplateVersion,
    HrOnboardingTaskDefinition, HrOnboardingMaterialRequirement, HrOnboardingTaskInstance,
    HrOnboardingMaterial, HrOnboardingAuditEvent, HrOnboardingCase, HrOnboardingIdempotencyRecord)
from hr_onboarding.services.school_template_service import (SchoolTemplateService, normalize_plan,
    validate_plan, verify_school_template, TemplateConfigurationError, MANAGE, PUBLISH)
from hr_onboarding.services.task_service import TaskService
from hr_onboarding.services.material_service import ensure_materials_from_requirements


def plan():
    return {'code':'TEACHER_JOIN','name':'教师入职办理','effective_from':'2026-01-01', 'effective_to':None,
        'scope':{'staff_categories':['TEACHER'],'employment_types':['FULL_TIME']},'note':'测试学校已确认清单；非生产制度',
        'tasks':[
            {'code':'ACCOUNT','title':'办理教职工账户','responsible_role':'IT_SERVICE','blocking_level':'BLOCKS_ONBOARDING_COMPLETE','due_offset_days':2},
            {'code':'CARD','title':'领取工作证','responsible_role':'RESPONSIBLE_HR','prerequisite_codes':['ACCOUNT'],'due_offset_days':3}],
        'materials':[{'material_type':'CERTIFICATE','label':'资格材料','required':True,'blocking_phase':'ACTIVATION','allowed_formats':['pdf'],'max_size_mb':10}]}


def user(name, codes):
    obj = get_user_model().objects.create_user(username=name, password='test-only-Strong!91')
    ct = ContentType.objects.get_for_model(HrOnboardingTemplate)
    for code in codes:
        perm, _ = Permission.objects.get_or_create(content_type=ct, codename=code, defaults={'name':code})
        obj.user_permissions.add(perm)
    return obj


class TemplateValidationTests(SimpleTestCase):
    def test_valid_plan(self): self.assertTrue(validate_plan(normalize_plan(plan()))['valid'])
    def test_cycle_is_found(self):
        p=plan();p['tasks'][0]['prerequisite_codes']=['CARD']
        self.assertFalse(validate_plan(normalize_plan(p))['valid'])
    def test_missing_prerequisite(self):
        p=plan();p['tasks'][1]['prerequisite_codes']=['MISSING']
        self.assertFalse(validate_plan(normalize_plan(p))['valid'])
    def test_duplicate_code(self):
        p=plan();p['tasks'][1]['code']='ACCOUNT'
        with self.assertRaises(TemplateConfigurationError):normalize_plan(p)
    def test_due_before_available(self):
        p=plan();p['tasks'][0]['available_offset_days']=4
        with self.assertRaises(TemplateConfigurationError):normalize_plan(p)
    def test_unknown_tenant_cannot_be_smuggled(self):
        p=plan();p['tenant_id']=2
        with self.assertRaises(TemplateConfigurationError):normalize_plan(p)
    def test_unknown_automated_handler_cannot_be_smuggled(self):
        p=plan();p['tasks'][0]['automation_handler']='os.system'
        with self.assertRaises(TemplateConfigurationError):normalize_plan(p)
    def test_date_end_is_exclusive(self):
        p=plan();p['effective_to']=p['effective_from']
        with self.assertRaises(TemplateConfigurationError):normalize_plan(p)
    def test_scope_uses_actual_enum(self):
        p=plan();p['scope']['staff_categories']=['SUPER_STAFF']
        with self.assertRaises(TemplateConfigurationError):normalize_plan(p)
    def test_unrestricted_scope_warns(self):
        p=plan();p['scope']={}
        self.assertTrue(any('全部人员' in s for s in validate_plan(normalize_plan(p))['warnings']))
    def test_false_string_rejected(self):
        p=plan();p['materials'][0]['required']='false'
        with self.assertRaises(TemplateConfigurationError):normalize_plan(p)
    def test_empty_upload_whitelist_rejected(self):
        p=plan();p['materials'][0]['allowed_formats']=[]
        with self.assertRaises(TemplateConfigurationError):normalize_plan(p)
    def test_unknown_format_rejected(self):
        p=plan();p['materials'][0]['allowed_formats']=['html']
        with self.assertRaises(TemplateConfigurationError):normalize_plan(p)
    def test_empty_plan_not_publishable(self):
        p=plan();p.update(tasks=[],materials=[])
        self.assertFalse(validate_plan(normalize_plan(p))['valid'])


@override_settings(AUTHENTICATION_BACKENDS=['base.auth_backends.CompanyScopedBackend'], COMPANY_SCOPED_PERMISSIONS=False)
class SchoolTemplateORMTests(TestCase):
    def setUp(self):
        self.maker=user('maker',[MANAGE,'hr05.case.create','hr05.case.view'])
        self.checker=user('checker',[PUBLISH,'hr05.case.view'])
        self.executor=user('executor',['hr05.task.complete'])
        self.case=HrOnboardingCase.objects.create(tenant_id=1,case_no='JOIN-001',source_type='LEGAL_MANUAL_MIGRATION',
            source_id='test-only',expected_report_date=date(2026,9,19),status='PREPARING')
    def svc(self, who=None, tenant=1):return SchoolTemplateService(tenant_id=tenant,user=who or self.maker,request_id='test-v10')
    def draft(self, data=None, key=None):return self.svc().save(plan=data or plan(),idempotency_key=key or uuid4().hex)['version']
    def published(self):
        d=self.draft();return self.svc(self.checker).publish(version_id=d['id'],etag=d['etag'],reason='校方制度核对',idempotency_key=uuid4().hex)['version']
    def bind(self,v,key=None):
        self.case.refresh_from_db()
        return self.svc().bind(version_id=v['id'],case_id=self.case.id,case_version=self.case.version,etag=v['etag'],idempotency_key=key or uuid4().hex)
    def test_save_only_draft_no_instances(self):
        d=self.draft();self.assertEqual(d['status'],'DRAFT');self.assertEqual(HrOnboardingTaskDefinition.objects.count(),0)
    def test_draft_save_replay(self):
        first=self.draft(key='once');again=self.svc().save(plan=plan(),idempotency_key='once')
        self.assertTrue(again['replayed']);self.assertEqual(first['id'],again['version']['id']);self.assertEqual(HrOnboardingTemplateVersion.objects.count(),1)
    def test_same_key_different_content(self):
        self.draft(key='once');p=plan();p['name']='其他方案'
        with self.assertRaises(IdempotencyConflictError):self.svc().save(plan=p,idempotency_key='once')
    def test_executor_not_configuration_manager(self):
        with self.assertRaises(PermissionDeniedError):self.svc(self.executor).save(plan=plan(),idempotency_key='x')
    def test_cross_school_get_returns_not_found(self):
        d=self.draft()
        with self.assertRaises(Hr05ApiError):self.svc(tenant=2).detail(d['id'])
    def test_list_does_not_return_foreign_templates(self):
        self.draft();self.assertEqual(self.svc(tenant=2).list()['total'],0)
    def test_stale_draft_etag_rejected(self):
        d=self.draft();p=plan();p['name']='修改'
        self.svc().save(plan=p,version_id=d['id'],etag=d['etag'],idempotency_key='edit')
        with self.assertRaises(VersionConflictError):self.svc().save(plan=plan(),version_id=d['id'],etag=d['etag'],idempotency_key='stale')
    def test_published_cannot_edit(self):
        v=self.published()
        with self.assertRaises(TemplateConfigurationError):self.svc().save(plan=plan(),version_id=v['id'],etag=v['etag'],idempotency_key='no')
    def test_independent_publisher_materializes_actual_definitions(self):
        v=self.published();self.assertEqual(HrOnboardingTaskDefinition.objects.count(),2);self.assertEqual(HrOnboardingMaterialRequirement.objects.count(),1)
        self.assertEqual(v['published_by'],self.checker.id)
    def test_self_publish_rejected_even_with_both_permissions(self):
        d=self.draft();self.maker.user_permissions.add(*self.checker.user_permissions.all());self.maker=get_user_model().objects.get(pk=self.maker.pk)
        with self.assertRaises(PermissionDeniedError):self.svc().publish(version_id=d['id'],etag=d['etag'],reason='自己',idempotency_key='no')
    def test_any_editor_cannot_publish(self):
        self.checker.user_permissions.add(*self.maker.user_permissions.all());self.checker=get_user_model().objects.get(pk=self.checker.pk)
        d=self.draft();e=self.svc(self.checker).save(plan=plan(),version_id=d['id'],etag=d['etag'],idempotency_key='edit')['version']
        with self.assertRaises(PermissionDeniedError):self.svc(self.checker).publish(version_id=e['id'],etag=e['etag'],reason='自己',idempotency_key='no')
    def test_bad_dag_blocks_publish(self):
        p=plan();p['tasks'][0]['prerequisite_codes']=['CARD'];d=self.draft(p)
        with self.assertRaises(TemplateConfigurationError):self.svc(self.checker).publish(version_id=d['id'],etag=d['etag'],reason='核对',idempotency_key='bad')
        self.assertFalse(HrOnboardingTaskDefinition.objects.exists())
    def test_audit_failure_rolls_back_publication_and_definitions(self):
        d=self.draft()
        with patch.object(HrOnboardingAuditEvent.objects,'create',side_effect=RuntimeError('storage')):
            with self.assertRaises(RuntimeError):self.svc(self.checker).publish(version_id=d['id'],etag=d['etag'],reason='核对',idempotency_key='bad')
        self.assertEqual(HrOnboardingTemplateVersion.objects.get(pk=d['id']).status,'DRAFT');self.assertEqual(HrOnboardingTaskDefinition.objects.count(),0)
    def test_publish_replay_creates_no_duplicate_definitions(self):
        d=self.draft();s=self.svc(self.checker);kw=dict(version_id=d['id'],etag=d['etag'],reason='核对',idempotency_key='pub')
        a=s.publish(**kw);b=s.publish(**kw);self.assertTrue(b['replayed']);self.assertEqual(a['receipt'],b['receipt']);self.assertEqual(HrOnboardingTaskDefinition.objects.count(),2)
    def test_overlap_versions_block(self):
        self.published();d=self.draft()
        with self.assertRaises(TemplateConfigurationError):self.svc(self.checker).publish(version_id=d['id'],etag=d['etag'],reason='重叠',idempotency_key='b')
    def test_preview_read_only(self):
        v=self.published();out=self.svc().preview(version_id=v['id'],case_id=self.case.id)
        self.assertTrue(out['eligible']);self.assertFalse(HrOnboardingTaskInstance.objects.exists());self.assertFalse(HrOnboardingMaterial.objects.exists())
    def test_draft_preview_not_eligible(self):
        v=self.draft();self.assertFalse(self.svc().preview(version_id=v['id'],case_id=self.case.id)['eligible'])
    def test_bind_initializes_existing_task_and_material_models(self):
        v=self.published();b=self.bind(v);self.case.refresh_from_db()
        self.assertEqual(str(self.case.template_version_id),v['id']);self.assertEqual(b['tasks_created'],2);self.assertEqual(b['materials_created'],1)
        self.assertEqual(self.case.status,'PREPARING');self.assertIsNone(self.case.hr03_staff_master_id)
    def test_bind_replay_preserves_counts(self):
        v=self.published();kw=dict(version_id=v['id'],case_id=self.case.id,case_version=self.case.version,etag=v['etag'],idempotency_key='bind')
        a=self.svc().bind(**kw);b=self.svc().bind(**kw);self.assertTrue(b['replayed']);self.assertEqual(a['receipt'],b['receipt']);self.assertEqual(HrOnboardingTaskInstance.objects.count(),2)
    def test_bind_audit_failure_rolls_back_all(self):
        v=self.published()
        with patch.object(HrOnboardingAuditEvent.objects,'create',side_effect=RuntimeError('storage')):
            with self.assertRaises(RuntimeError):self.bind(v)
        self.case.refresh_from_db();self.assertIsNone(self.case.template_version_id);self.assertFalse(HrOnboardingTaskInstance.objects.exists());self.assertFalse(HrOnboardingMaterial.objects.exists())
    def test_case_stale_version_rejected(self):
        v=self.published();self.case.version=2;self.case.save()
        with self.assertRaises(VersionConflictError):self.svc().bind(version_id=v['id'],case_id=self.case.id,case_version=1,etag=v['etag'],idempotency_key='a')
    def test_second_bind_never_replaces_pinned_version(self):
        v=self.published();self.bind(v)
        with self.assertRaises(TemplateConfigurationError):self.bind(v)
    def test_staff_scope_mismatch(self):
        v=self.published();self.case.staff_category='ADMIN';self.case.save()
        self.assertFalse(self.svc().preview(version_id=v['id'],case_id=self.case.id)['eligible'])
    def test_missing_report_date_blocks(self):
        v=self.published();self.case.expected_report_date=None;self.case.save()
        with self.assertRaises(TemplateConfigurationError):self.bind(v)
    def test_end_date_excluded(self):
        p=plan();p['effective_to']='2026-09-19';d=self.draft(p)
        v=self.svc(self.checker).publish(version_id=d['id'],etag=d['etag'],reason='截止',idempotency_key='p')['version']
        with self.assertRaises(TemplateConfigurationError):self.bind(v)
    def test_active_case_not_rebound(self):
        v=self.published();self.case.status='ACTIVE';self.case.save()
        with self.assertRaises(TemplateConfigurationError):self.bind(v)
    def test_formal_person_link_blocks_even_if_status_old(self):
        v=self.published();self.case.hr03_person_id=uuid4();self.case.save()
        with self.assertRaises(TemplateConfigurationError):self.bind(v)
    def test_foreign_case_not_bound(self):
        v=self.published();self.case.tenant_id=2;self.case.save()
        with self.assertRaises(Hr05ApiError):self.bind(v)
    def test_tampered_definition_blocks_read_and_binding(self):
        v=self.published();HrOnboardingTaskDefinition.objects.filter(template_version_id=v['id']).update(title='非法变化')
        with self.assertRaises(TemplateConfigurationError):self.svc().detail(v['id'])
        with self.assertRaises(TemplateConfigurationError):self.bind(v)
    def test_retire_preserves_old_cases_and_definitions(self):
        v=self.published();self.bind(v)
        self.svc(self.checker).retire(version_id=v['id'],etag=v['etag'],reason='启用下一版',idempotency_key='stop')
        self.case.refresh_from_db();self.assertEqual(str(self.case.template_version_id),v['id'])
        verify_school_template(self.case.template_version,1)
        self.assertEqual(TaskService(tenant_id=1).instantiate_tasks(self.case),0)
    def test_new_version_does_not_change_old_case(self):
        v=self.published();self.bind(v);self.svc(self.checker).retire(version_id=v['id'],etag=v['etag'],reason='替代',idempotency_key='stop')
        p=plan();p['tasks'][0]['title']='新版账户办理';d=self.draft(p)
        self.svc(self.checker).publish(version_id=d['id'],etag=d['etag'],reason='新版',idempotency_key='new')
        self.case.refresh_from_db();self.assertEqual(str(self.case.template_version_id),v['id'])
        self.assertEqual(self.case.template_version.task_definitions.get(code='ACCOUNT').title,'办理教职工账户')
    def test_legacy_version_retains_legacy_behavior(self):
        t=HrOnboardingTemplate.objects.create(tenant_id=1,code='OLD',name='历史')
        v=HrOnboardingTemplateVersion.objects.create(tenant_id=1,template=t,status='ACTIVE')
        verify_school_template(v,1)
        with self.assertRaises(TemplateConfigurationError):self.svc().detail(v.id)
    def test_page_size_is_bounded(self):
        with self.assertRaises(TemplateConfigurationError):self.svc().list(page_size=1000)


@override_settings(AUTHENTICATION_BACKENDS=['base.auth_backends.CompanyScopedBackend'], COMPANY_SCOPED_PERMISSIONS=False)
@override_settings(MIDDLEWARE=['django.contrib.sessions.middleware.SessionMiddleware','django.contrib.auth.middleware.AuthenticationMiddleware','django.middleware.csrf.CsrfViewMiddleware'])
class SchoolTemplateHTTPTests(TestCase):
    def setUp(self):
        self.maker=user('http-maker',[MANAGE,'hr05.case.view','hr05.case.create'])
        self.client=Client();self.assertTrue(self.client.login(username='http-maker',password='test-only-Strong!91'))
        self.membership=patch('base.auth_backends.get_allowed_company_ids',return_value={1});self.membership.start();self.addCleanup(self.membership.stop)
        self.tenant=patch('hr_onboarding.api.base.resolve_tenant_from_request',return_value=1);self.tenant.start();self.addCleanup(self.tenant.stop)
        s=self.client.session;s['selected_company']='1';s.save()
    def test_real_login_read(self):
        r=self.client.get('/api/hr/v1/onboarding/school-templates');self.assertEqual(r.status_code,200,r.content)
    def test_real_login_save_and_detail(self):
        r=self.client.post('/api/hr/v1/onboarding/school-templates/save',data=json.dumps({'plan':plan()}),content_type='application/json',HTTP_IDEMPOTENCY_KEY='http')
        self.assertEqual(r.status_code,200,r.content);pk=r.json()['data']['version']['id']
        self.assertEqual(self.client.get('/api/hr/v1/onboarding/school-templates/'+pk).status_code,200)
    def test_cross_company_membership_denied(self):
        with patch('base.auth_backends.get_allowed_company_ids',return_value={2}):
            self.assertEqual(self.client.get('/api/hr/v1/onboarding/school-templates').status_code,403)
    def test_unauthenticated_denied(self):
        self.client.logout();self.assertEqual(self.client.get('/api/hr/v1/onboarding/school-templates').status_code,403)
    def test_no_configuration_permission_denied(self):
        self.maker.user_permissions.clear();self.assertEqual(self.client.get('/api/hr/v1/onboarding/school-templates').status_code,403)
    def test_csrf_not_bypassed(self):
        c=Client(enforce_csrf_checks=True);c.force_login(self.maker)
        s=c.session;s['selected_company']='1';s.save()
        self.assertEqual(c.post('/api/hr/v1/onboarding/school-templates/save',data=json.dumps({'plan':plan()}),content_type='application/json',HTTP_IDEMPOTENCY_KEY='csrf').status_code,403)
    def test_client_actor_field_rejected(self):
        r=self.client.post('/api/hr/v1/onboarding/school-templates/save',data=json.dumps({'plan':plan(),'actor':1}),content_type='application/json',HTTP_IDEMPOTENCY_KEY='forged')
        self.assertEqual(r.status_code,400)
    def test_get_does_not_create(self):
        self.client.get('/api/hr/v1/onboarding/school-templates')
        self.assertEqual(HrOnboardingTemplate.objects.count(),0);self.assertEqual(HrOnboardingAuditEvent.objects.count(),0)

    def test_invalid_version_body_is_rejected_not_server_error(self):
        r=self.client.post('/api/hr/v1/onboarding/school-templates/save', data=json.dumps({'plan':plan(),'version_id':'not-a-uuid'}),content_type='application/json',HTTP_IDEMPOTENCY_KEY='bad-id')
        self.assertEqual(r.status_code,400)
    def test_page_sets_real_csrf_cookie(self):
        response=self.client.get('/hr/onboarding/school-templates')
        self.assertEqual(response.status_code,200)
        self.assertIn('csrftoken',response.cookies)
    def test_page_other_school_membership_is_forbidden(self):
        with patch('base.auth_backends.get_allowed_company_ids',return_value={2}):
            self.assertEqual(self.client.get('/hr/onboarding/school-templates').status_code,403)
    def test_department_scope_cannot_configure_school_plan(self):
        r=self.client.get('/api/hr/v1/onboarding/school-templates',{'scope_type':'COLLEGE','scope_id':'11'})
        self.assertEqual(r.status_code,403)
