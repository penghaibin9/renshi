"""Real Django/MySQL gates. Not a source/mock substitute for database execution."""
import os
from io import StringIO
from unittest.mock import patch
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import TestCase, override_settings, RequestFactory
from base.models import Company, SchoolBootstrapState
from base.first_use import build_first_use, resolve_admin_school
from employee.models import Employee
from horilla_auth.models import HorillaUser
from horilla.horilla_middlewares import tenant_context

PASSWORD = 'Minimal-First-Use!9y7Q3r5T8z'

@override_settings(IS_PRODUCTION=True, HR_INSTALLATION_MODE='standalone_school')
class MinimalSchoolBootstrapMySQLTests(TestCase):
    def setUp(self):
        self.assertEqual(connection.vendor,'mysql','This acceptance gate requires real MySQL; no SQLite pass.')

    def run_bootstrap(self):
        out=StringIO()
        with patch.dict(os.environ,{'HR_BOOTSTRAP_ADMIN_PASSWORD':PASSWORD}):
            call_command('bootstrap_production_admin',
                company_name='首次启用验收学校',first_name='首位管理员',email='school-admin@example.edu.cn',stdout=out)
        return out.getvalue()

    def test_minimal_bootstrap_no_fake_profile_or_teacher(self):
        self.run_bootstrap()
        school=Company.objects.get()
        self.assertEqual([school.address,school.country,school.state,school.city,school.zip],['']*5)
        user=HorillaUser.objects.get(username='school-admin@example.edu.cn')
        self.assertTrue(user.check_password(PASSWORD))
        employee=Employee.objects.entire().get(employee_user_id=user)
        self.assertEqual(employee.phone,'');self.assertIsNone(employee.gender)
        self.assertEqual(employee.employee_work_info.company_id_id,school.pk)
        receipt=SchoolBootstrapState.objects.get(pk=1)
        self.assertEqual((receipt.company_id,receipt.administrator_id),(school.pk,user.pk))
        request=RequestFactory().get('/settings/system-management/');request.user=user
        with tenant_context(school.pk): result=build_first_use(request,school)
        self.assertEqual(next(s for s in result['steps'] if s['code']=='staff')['state'],'pending')
        self.assertFalse(result['production_accepted'])

    def test_rerun_after_profile_supplement_does_not_erase(self):
        self.run_bootstrap();school=Company.objects.get();school.address='学校后来填写的真实地址';school.save()
        self.assertIn('ALREADY_COMPLETE',self.run_bootstrap())
        school.refresh_from_db();self.assertEqual(school.address,'学校后来填写的真实地址')
        self.assertEqual(Company.objects.count(),1)

    def test_rollback_on_employee_failure_leaves_no_school_or_user(self):
        with patch('employee.models.Employee.save',side_effect=RuntimeError('injected transaction failure')):
            with self.assertRaises(RuntimeError):self.run_bootstrap()
        self.assertFalse(Company.objects.exists())
        self.assertFalse(HorillaUser.objects.filter(username='school-admin@example.edu.cn').exists())
        self.assertFalse(SchoolBootstrapState.objects.filter(company__isnull=False).exists())

    def test_unbound_user_never_gets_single_school_fallback(self):
        self.run_bootstrap()
        user=HorillaUser.objects.create_user(username='unbound',password=PASSWORD)
        request=RequestFactory().get('/');request.user=user
        self.assertIsNone(resolve_admin_school(request))

    def test_fresh_legacy_migration_has_no_account_side_effect(self):
        if 'auth_user' in connection.introspection.table_names():
            self.fail('Fresh-install gate requires a new database without auth_user legacy tables.')
        out=StringIO();call_command('migrateusers',stdout=out)
        self.assertIn('LEGACY_USERS_NOT_PRESENT',out.getvalue())
        self.assertFalse(HorillaUser.objects.exists())
