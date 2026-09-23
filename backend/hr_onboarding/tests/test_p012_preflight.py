"""P012 read-only preflight guards; uses SQLite solely to test refusal/reporting."""
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from django.test import TestCase, override_settings
from django.core.management import call_command, CommandError
from django.db import connection
from django.test.utils import CaptureQueriesContext
from hr_onboarding.management.commands.hr_first_delivery_check import collect_report

class P012PreflightTests(TestCase):
    def codes(self):
        return {x['id']: x['status'] for x in collect_report(1)['checks']}
    def test_non_none_migration_replacement_is_blocked(self):
        with override_settings(MIGRATION_MODULES={'hr_onboarding':'fake.migrations'}):
            self.assertEqual(self.codes()['MIGRATION_OVERRIDES'],'BLOCKED')
    def test_reduced_settings_are_not_canonical(self):
        self.assertEqual(self.codes()['CANONICAL_SETTINGS'],'BLOCKED')
    def test_reduced_urlconf_is_not_canonical(self):
        self.assertEqual(self.codes()['CANONICAL_ROUTES'],'BLOCKED')
    def test_reduced_registry_is_not_all_hr_apps(self):
        self.assertEqual(self.codes()['CANONICAL_HR_APPS'],'BLOCKED')
    def test_wrong_middleware_order_is_blocked(self):
        # Metadata-only override: do not instantiate these middlewares or claim auth.
        with override_settings(MIDDLEWARE=[
            'platform_access.middleware.SafeCompanyMiddleware',
            'django.contrib.sessions.middleware.SessionMiddleware',
            'django.contrib.auth.middleware.AuthenticationMiddleware']):
            self.assertEqual(self.codes()['TENANT_MIDDLEWARE_ORDER'],'BLOCKED')
    def test_missing_mfa_is_blocked(self):
        with override_settings(TWO_FACTORS_AUTHENTICATION=False):
            self.assertEqual(self.codes()['MFA_ENABLED'],'BLOCKED')
    def test_missing_scan_is_blocked(self):
        with override_settings(MALWARE_SCAN_REQUIRED=False):
            self.assertEqual(self.codes()['UPLOAD_SCAN_REQUIRED'],'BLOCKED')
    def test_missing_tenant_fence_is_blocked(self):
        with override_settings(TENANT_FAIL_CLOSED=False):
            self.assertEqual(self.codes()['TENANT_FAIL_CLOSED'],'BLOCKED')
    def test_database_check_makes_no_business_writes(self):
        with CaptureQueriesContext(connection) as q:
            collect_report(1)
        self.assertFalse(any(row['sql'].lstrip().upper().startswith(('INSERT','UPDATE','DELETE','DROP','ALTER','CREATE')) for row in q))
    def test_no_unperformed_gate_can_turn_green(self):
        result=collect_report(1); codes={x['id']:x['status'] for x in result['checks']}
        for code in ('LOCK_RUNTIME','PRIVATE_FILES','REAL_LOGIN','CLIENT_SIGNOFF'):
            self.assertEqual(codes[code],'NOT_VERIFIED')
        self.assertFalse(result['release_approved'])
    def test_unknown_school_is_not_verified(self):
        result=collect_report(999999999)
        codes={x['id']:x['status'] for x in result['checks']}
        self.assertEqual(codes['SCHOOL_EXISTS'],'BLOCKED')
    def test_report_private_and_atomic(self):
        with TemporaryDirectory() as d:
            file=Path(d)/'report.json';file.write_text('previous')
            with self.assertRaises(CommandError):
                call_command('hr_first_delivery_check',tenant_id=1,report=str(file))
            self.assertEqual(file.stat().st_mode & 0o777,0o600)
            self.assertEqual(json.loads(file.read_text())['mode'],'READ_ONLY')
            self.assertEqual(list(Path(d).glob('.hr-preflight-*')),[])
    def test_invalid_school_id_writes_no_report(self):
        with TemporaryDirectory() as d:
            file=Path(d)/'report.json'
            with self.assertRaises(CommandError):
                call_command('hr_first_delivery_check',tenant_id=0,report=str(file))
            self.assertFalse(file.exists())
    def test_secret_values_not_in_report(self):
        with override_settings(SECRET_KEY='p012-secret-do-not-export-XY341'):
            self.assertNotIn('p012-secret-do-not-export-XY341',json.dumps(collect_report(1)))
