"""Keep live company authorization while bounding one-permission lookups.

A settings page can ask hundreds of questions. None should deserialize the
account's entire permission catalogue. Real MySQL tests compare the optimized
lookup against the prior full-set decision, including non-transitive aliases.
"""
from contextlib import contextmanager
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.test import Client, TestCase, override_settings

from base.auth_backends import CompanyScopedBackend
from base.models import Company, CompanyGroupAssignment
from horilla.horilla_middlewares import current_company_id
from horilla.hr_permissions import is_semantic_hr_permission, permission_aliases


@contextmanager
def scope(value):
    token = current_company_id.set(value)
    try:
        yield
    finally:
        current_company_id.reset(token)


@override_settings(COMPANY_SCOPED_PERMISSIONS=True, TENANT_FAIL_CLOSED=True,
                   ALLOWED_HOSTS=['testserver'])
class PermissionLookupTests(TestCase):
    def setUp(self):
        self.backend = CompanyScopedBackend()
        self.user = get_user_model().objects.create_user(username='lookup-admin', password='unused-fixture')
        self.user.is_new_employee = False
        self.user.save(update_fields=['is_new_employee'])
        self.a = Company.objects.create(company='Lookup School A', address='A', country='CN', state='HN', city='CS', zip='410000')
        self.b = Company.objects.create(company='Lookup School B', address='B', country='CN', state='HN', city='CS', zip='410001')
        self.group = Group.objects.create(name='lookup-a')
        self.group_b = Group.objects.create(name='lookup-b')
        CompanyGroupAssignment.objects.create(user=self.user, company=self.a, group=self.group)
        CompanyGroupAssignment.objects.create(user=self.user, company=self.b, group=self.group_b)
        self.ct = ContentType.objects.get_for_model(Company)

    def permission(self, codename, *, app=None):
        content_type = self.ct if app is None else ContentType.objects.get_or_create(app_label=app, model='lookup_fixture')[0]
        return Permission.objects.get_or_create(content_type=content_type, codename=codename, defaults={'name': codename})[0]

    def old_decision(self, code):
        values = self.backend.get_all_permissions(self.user)
        return bool(permission_aliases(code) & values) if is_semantic_hr_permission(code) else code in values

    def test_live_grants_and_scope_changes_do_not_reuse_cached_access(self):
        permission = self.permission('view_company')
        self.group.permissions.add(permission)
        with scope(self.a.pk):
            self.assertTrue(self.backend.has_perm(self.user, 'base.view_company'))
            self.group.permissions.remove(permission)
            self.assertFalse(self.backend.has_perm(self.user, 'base.view_company'))
            self.group.permissions.add(permission)
            self.assertTrue(self.backend.has_perm(self.user, 'base.view_company'))
        with scope(self.b.pk):
            self.assertFalse(self.backend.has_perm(self.user, 'base.view_company'))
        with scope(self.a.pk):
            self.assertTrue(self.backend.has_perm(self.user, 'base.view_company'))
            self.user.company_group_assignments.filter(company=self.a).delete()
            self.assertFalse(self.backend.has_perm(self.user, 'base.view_company'))

    def test_missing_and_union_scope_preserve_the_existing_intersection(self):
        permission = self.permission('hr.staff.view')
        self.group.permissions.add(permission)
        for selected in (None, 'all', self.b.pk):
            with self.subTest(selected=selected), scope(selected):
                self.assertFalse(self.backend.has_perm(self.user, 'hr.staff.view'))
        self.group_b.permissions.add(permission)
        with scope('all'):
            self.assertTrue(self.backend.has_perm(self.user, 'hr.staff.view'))
            self.group_b.permissions.remove(permission)
            self.assertFalse(self.backend.has_perm(self.user, 'hr.staff.view'))

    def test_all_existing_alias_edges_match_the_prior_full_set_decision(self):
        codes = (
            'hr.staff.view', 'hr03.view',
            'hr04.assessment.score_override', 'hr.recruitment.assessment.score.override',
            'hr.recruitment.assessment.score_override', 'hr04.assessment.score.override',
            'hr04.handoff_hr05', 'hr.recruitment.handoff_hr05.execute',
            'hr04.handoff_hr05.execute', 'hr.recruitment.handoff_hr05',
            'hr05.export', 'hr.onboarding.export.standard', 'hr.onboarding.export',
            'hr05.export.standard', 'hr.onboarding.export.sensitive', 'hr05.sensitive_export',
        )
        with scope(self.a.pk):
            for granted in codes:
                self.group.permissions.set([self.permission(granted)])
                full = self.backend.get_all_permissions(self.user)
                for requested in codes:
                    with self.subTest(granted=granted, requested=requested):
                        expected = bool(permission_aliases(requested) & full)
                        self.assertEqual(self.backend.has_perm(self.user, requested), expected)

    def test_raw_django_spellings_and_semantic_shaped_app_labels_are_preserved(self):
        permissions = [self.permission('view_company'), self.permission('hr.staff.view'),
                       self.permission('staff.view', app='hr')]
        self.group.permissions.set(permissions)
        codes = ('base.view_company', 'other.view_company', 'base.hr.staff.view',
                 'hr.staff.view', 'hr03.view', 'BASE.view_company', 'base.VIEW_COMPANY',
                 'HR.staff.view', 'hr.staff.VIEW', 'view_company', '')
        with scope(self.a.pk):
            for code in codes:
                with self.subTest(code=code):
                    self.assertEqual(self.backend.has_perm(self.user, code), self.old_decision(code))

    def test_single_lookup_does_not_materialize_thousands_of_unrelated_grants(self):
        Permission.objects.bulk_create([
            Permission(content_type=self.ct, codename=f'lookup_unrelated_{i}', name='Synthetic unrelated grant')
            for i in range(2200)
        ], batch_size=500)
        self.group.permissions.set(Permission.objects.filter(content_type=self.ct))
        with scope(self.a.pk):
            with patch.object(Permission, 'from_db', wraps=Permission.from_db) as loaded:
                self.assertTrue(self.old_decision('base.view_company'))
                old_rows = loaded.call_count
            with patch.object(Permission, 'from_db', wraps=Permission.from_db) as loaded:
                self.assertTrue(self.backend.has_perm(self.user, 'base.view_company'))
                self.assertEqual(loaded.call_count, 1)
            self.assertGreaterEqual(old_rows, 2200)
            with patch.object(Permission, 'from_db', wraps=Permission.from_db) as loaded:
                self.assertFalse(self.backend.has_perm(self.user, 'base.lookup_absent'))
                self.assertEqual(loaded.call_count, 0)

    def test_inactive_anonymous_and_object_permissions_remain_denied(self):
        from django.contrib.auth.models import AnonymousUser
        self.group.permissions.add(self.permission('view_company'))
        with scope(self.a.pk):
            self.assertFalse(self.backend.has_perm(AnonymousUser(), 'base.view_company'))
            self.assertFalse(self.backend.has_perm(self.user, 'base.view_company', obj=self.a))
            self.user.is_active = False
            self.assertFalse(self.backend.has_perm(self.user, 'base.view_company'))
            self.user.is_superuser = True
            self.assertFalse(self.backend.has_perm(self.user, 'base.view_company'))

    def test_direct_global_grant_cannot_bypass_school_scope(self):
        self.user.user_permissions.add(self.permission('change_company'))
        with scope(self.a.pk):
            self.assertFalse(self.backend.has_perm(self.user, 'base.change_company'))

    @override_settings(COMPANY_SCOPED_PERMISSIONS=False)
    def test_legacy_mode_keeps_direct_and_global_group_behavior(self):
        permission = self.permission('view_company')
        self.user.user_permissions.add(permission)
        self.user.groups.add(self.group)
        self.group.permissions.add(self.permission('hr.staff.view'))
        with scope(None):
            for code in ('base.view_company', 'hr.staff.view', 'base.no_such_permission'):
                self.assertEqual(self.backend.has_perm(self.user, code), self.old_decision(code))

    def test_full_school_settings_read_uses_ordinary_wide_role(self):
        # This is the same role shape as the failing browser inventory. No
        # Employee or prebuilt business facts are necessary to view this page.
        self.group.permissions.set(Permission.objects.all())
        self.user.company_group_assignments.filter(company=self.b).delete()
        browser = Client()
        self.assertTrue(browser.login(username=self.user.username, password='unused-fixture'))
        with patch.object(Permission, 'from_db', wraps=Permission.from_db) as loaded:
            response = browser.get('/settings/school-management/', HTTP_HX_REQUEST='true',
                                   HTTP_HX_BOOSTED='true', HTTP_HX_TARGET='settingsContainer',
                                   HTTP_HX_SIDEBAR_NAV='true')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="school-management"')
        self.assertFalse(self.user.is_superuser)
        # Full permission enumeration may still be needed for menu discovery;
        # it must not be repeated for every has_perm call (previously >100x).
        self.assertLess(loaded.call_count, Permission.objects.count() * 10)
