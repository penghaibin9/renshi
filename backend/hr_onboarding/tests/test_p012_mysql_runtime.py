"""Real MySQL/canonical-settings-only P1 proof. No auth or database substitutes.

Execute only via scripts/run_hr_p012_gate.py in its new isolated test schema.
SQLite discovery reports explicit SKIPs, not passes. This suite does not prove
native-browser login/MFA or a complete HR01-HR18 workflow. No outbound providers.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import date
import os
import threading
from unittest import skipUnless
from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import connection, connections
from django.test import TransactionTestCase


@contextmanager
def school_context(school_id):
    from horilla.horilla_middlewares import current_company_id, set_selected_company
    token=set_selected_company(school_id)
    try:
        yield
    finally:
        current_company_id.reset(token)


def sample_plan():
    return {'code':'P012_NEW_JOIN','name':'隔离学校入职校验','note':'隔离校验，非校方生产制度',
        'effective_from':'2026-01-01','effective_to':None,
        'scope':{'staff_categories':['TEACHER'],'employment_types':['FULL_TIME']},
        'tasks':[{'code':'ACCOUNT','title':'核验账户办理凭证','responsible_role':'IT_SERVICE',
                  'blocking_level':'BLOCKS_ONBOARDING_COMPLETE','due_offset_days':2},
                 {'code':'CARD','title':'核验身份卡办理凭证','responsible_role':'RESPONSIBLE_HR',
                  'prerequisite_codes':['ACCOUNT'],'due_offset_days':3}],
        'materials':[{'material_type':'CERTIFICATE','label':'资格核验材料','required':True,
                      'blocking_phase':'ACTIVATION','allowed_formats':['pdf'],'max_size_mb':10}]}


@skipUnless(connection.vendor=='mysql','P012 MySQL-only: SQLite cannot prove these gates')
class P012CanonicalMySQLTests(TransactionTestCase):
    @classmethod
    def setUpClass(cls):
        # Fail, not skip, when a supposed MySQL run weakens the production boundary.
        if os.environ.get('HR_ACCEPTANCE_ISOLATED')!='YES':
            raise ImproperlyConfigured('P012 needs the fresh isolated acceptance runner')
        if getattr(settings,'SETTINGS_MODULE','')!='horilla.settings':
            raise ImproperlyConfigured('P012 refuses replacement settings')
        if not str(connection.settings_dict['NAME']).startswith('test_'):
            raise ImproperlyConfigured('P012 must never write to a non-test schema')
        if getattr(settings,'MIGRATION_MODULES',{}) or not settings.COMPANY_SCOPED_PERMISSIONS or not settings.TENANT_FAIL_CLOSED:
            raise ImproperlyConfigured('P012 requires full migrations and real school-scoped grants')
        if 'base.auth_backends.CompanyScopedBackend' not in settings.AUTHENTICATION_BACKENDS:
            raise ImproperlyConfigured('P012 requires the production permission backend')
        super().setUpClass()

    def setUp(self):
        from django.contrib.auth import get_user_model
        from django.contrib.auth.models import Group, Permission
        from base.models import Company, CompanyGroupAssignment
        from hr_onboarding.models import HrOnboardingCase
        self.User=get_user_model(); self.Permission=Permission
        self.Assignment=CompanyGroupAssignment
        self.school=Company.objects.create(company='P012-'+uuid4().hex[:16])
        self.other=Company.objects.create(company='P012-'+uuid4().hex[:16])
        self.maker=self.User.objects.create_user(username='p012-maker',password='Only-Isolated-Tests!314')
        self.checker=self.User.objects.create_user(username='p012-checker',password='Only-Isolated-Tests!314')
        self.foreign=self.User.objects.create_user(username='p012-foreign',password='Only-Isolated-Tests!314')
        def grant(user, school, codes):
            group=Group.objects.create(name='P012-'+uuid4().hex)
            for code in codes:
                permissions=Permission.objects.filter(codename=code)
                if not permissions.exists():
                    self.fail('Original migration did not create permission: '+code)
                group.permissions.add(*permissions)
            CompanyGroupAssignment.objects.create(user=user,company=school,group=group)
        grant(self.maker,self.school,['hr05.template.manage','hr05.case.view','hr05.case.create'])
        grant(self.checker,self.school,['hr05.template.publish','hr05.case.view'])
        grant(self.foreign,self.other,['hr05.template.manage','hr05.case.view','hr05.case.create'])
        self.case=HrOnboardingCase.objects.create(tenant_id=self.school.pk,case_no='P012-CASE',
            source_type='LEGAL_MANUAL_MIGRATION',source_id='ISOLATED_TEST',
            expected_report_date=date(2026,9,19),staff_category='TEACHER',employment_type='FULL_TIME',status='PREPARING')

    def svc(self, who=None, school=None):
        from hr_onboarding.services.school_template_service import SchoolTemplateService
        return SchoolTemplateService(tenant_id=school or self.school.pk,user=who or self.maker,request_id='p012-runtime')

    def draft(self):
        with school_context(self.school.pk):
            return self.svc().save(plan=sample_plan(),idempotency_key=uuid4().hex)['version']

    def published(self):
        draft=self.draft()
        with school_context(self.school.pk):
            return self.svc(self.checker).publish(version_id=draft['id'],etag=draft['etag'],reason='隔离复核',idempotency_key=uuid4().hex)['version']

    def test_mysql_84_and_real_row_locks(self):
        with connection.cursor() as cursor:
            cursor.execute('SELECT VERSION(),@@foreign_key_checks')
            version,fk=cursor.fetchone()
        self.assertTrue(str(version).startswith('8.4.'));self.assertEqual(fk,1)
        self.assertTrue(connection.features.has_select_for_update)

    def test_password_authenticates_but_grants_are_school_scoped(self):
        from django.contrib.auth import authenticate
        actor=authenticate(username='p012-maker',password='Only-Isolated-Tests!314')
        self.assertEqual(actor.pk,self.maker.pk);self.assertFalse(actor.is_superuser)
        with school_context(self.school.pk):self.assertTrue(actor.has_perm('hr05.template.manage'))
        with school_context(self.other.pk):self.assertFalse(actor.has_perm('hr05.template.manage'))
        with school_context(None):self.assertFalse(actor.has_perm('hr05.template.manage'))

    def test_global_direct_grant_cannot_bypass_school_assignment(self):
        self.foreign.user_permissions.add(*self.Permission.objects.filter(codename='hr05.template.manage'))
        with school_context(self.school.pk):
            self.assertFalse(self.foreign.has_perm('hr05.template.manage'))

    def test_independent_publication_materializes_definitions_once(self):
        from hr_onboarding.models import HrOnboardingTaskDefinition, HrOnboardingMaterialRequirement
        draft=self.draft();kw=dict(version_id=draft['id'],etag=draft['etag'],reason='隔离复核',idempotency_key='P012-PUBLISH')
        with school_context(self.school.pk):
            first=self.svc(self.checker).publish(**kw);second=self.svc(self.checker).publish(**kw)
        self.assertTrue(second['replayed']);self.assertEqual(first['receipt'],second['receipt'])
        self.assertEqual(HrOnboardingTaskDefinition.objects.filter(template_version_id=draft['id']).count(),2)
        self.assertEqual(HrOnboardingMaterialRequirement.objects.filter(template_version_id=draft['id']).count(),1)

    def test_editor_cannot_publish_even_with_real_publish_grant(self):
        from hr_onboarding.api.exceptions import PermissionDeniedError
        draft=self.draft()
        assignment=self.Assignment.objects.filter(user=self.maker,company=self.school).first()
        assignment.group.permissions.add(*self.Permission.objects.filter(codename='hr05.template.publish'))
        with school_context(self.school.pk), self.assertRaises(PermissionDeniedError):
            self.svc().publish(version_id=draft['id'],etag=draft['etag'],reason='自己复核',idempotency_key='P012-NO')

    def test_foreign_tenant_record_is_not_read(self):
        from hr_onboarding.api.exceptions import Hr05ApiError
        draft=self.draft()
        with school_context(self.other.pk), self.assertRaises(Hr05ApiError):
            self.svc(self.foreign,self.other.pk).detail(draft['id'])

    def test_preview_is_read_only_and_old_case_remains_pinned(self):
        from hr_onboarding.models import HrOnboardingTaskInstance,HrOnboardingMaterial
        from hr_onboarding.services.school_template_service import verify_school_template
        version=self.published()
        with school_context(self.school.pk):
            self.assertTrue(self.svc().preview(version_id=version['id'],case_id=self.case.id)['eligible'])
            self.assertEqual(HrOnboardingTaskInstance.objects.filter(case=self.case).count(),0)
            self.svc().bind(version_id=version['id'],case_id=self.case.id,case_version=self.case.version,
                            etag=version['etag'],idempotency_key='P012-BIND')
            self.svc(self.checker).retire(version_id=version['id'],etag=version['etag'],reason='停止新单',idempotency_key='P012-RETIRE')
        self.case.refresh_from_db()
        self.assertEqual(str(self.case.template_version_id),version['id'])
        verify_school_template(self.case.template_version,self.school.pk)
        self.assertEqual(HrOnboardingTaskInstance.objects.filter(case=self.case).count(),2)
        self.assertEqual(HrOnboardingMaterial.objects.filter(case=self.case).count(),1)

    def _parallel(self, operation):
        barrier=threading.Barrier(2)
        def one(n):
            connections.close_all()
            try:
                with school_context(self.school.pk):
                    actor=self.User.objects.get(pk=self.maker.pk)
                    barrier.wait(timeout=15)
                    return operation(n,actor)
            finally:connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures=[executor.submit(one,n) for n in range(2)]
            return [future.result(timeout=45) for future in futures]

    def test_same_key_concurrent_bind_one_receipt(self):
        from hr_onboarding.models import HrOnboardingTaskInstance
        version=self.published()
        kwargs=dict(version_id=version['id'],case_id=self.case.id,case_version=self.case.version,
                    etag=version['etag'],idempotency_key='P012-CONCURRENT-SAME')
        results=self._parallel(lambda n,actor:self.svc(actor).bind(**kwargs))
        self.assertEqual(len({r['receipt'] for r in results}),1)
        self.assertEqual(sum(r['replayed'] for r in results),1)
        self.assertEqual(HrOnboardingTaskInstance.objects.filter(case=self.case).count(),2)

    def test_different_key_concurrent_bind_rejects_stale_version(self):
        from hr_onboarding.api.exceptions import VersionConflictError
        from hr_onboarding.models import HrOnboardingTaskInstance
        version=self.published()
        def attempt(n,actor):
            try:
                self.svc(actor).bind(version_id=version['id'],case_id=self.case.id,case_version=self.case.version,
                                     etag=version['etag'],idempotency_key='P012-COMPETE-'+str(n))
                return 'BOUND'
            except VersionConflictError:return 'STALE_REJECTED'
        self.assertCountEqual(self._parallel(attempt),['BOUND','STALE_REJECTED'])
        self.assertEqual(HrOnboardingTaskInstance.objects.filter(case=self.case).count(),2)
