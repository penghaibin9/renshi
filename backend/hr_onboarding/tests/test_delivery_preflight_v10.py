import json
from pathlib import Path
from tempfile import TemporaryDirectory
from django.test import TestCase
from django.core.management import call_command, CommandError
from django.db import connection
from django.test.utils import CaptureQueriesContext
from hr_onboarding.management.commands.hr_first_delivery_check import collect_report

class DeliveryPreflightTests(TestCase):
    def test_sqlite_and_test_settings_never_mark_production_ready(self):
        r=collect_report(1)
        self.assertEqual(r['overall'],'BLOCKED');self.assertFalse(r['release_approved'])
        codes={x['id']:x['status'] for x in r['checks']}
        self.assertEqual(codes['DB_ENGINE'],'BLOCKED')
        self.assertEqual(codes['MIGRATION_OVERRIDES'],'BLOCKED')
        self.assertEqual(codes['CLIENT_SIGNOFF'],'NOT_VERIFIED')
    def test_no_database_mutation(self):
        with CaptureQueriesContext(connection) as queries:
            collect_report(1)
        writes=[x['sql'] for x in queries if x['sql'].lstrip().upper().startswith(('INSERT','UPDATE','DELETE','DROP','CREATE','ALTER'))]
        self.assertEqual(writes,[])
    def test_command_writes_evidence_and_exits_nonzero(self):
        with TemporaryDirectory() as d:
            p=Path(d)/'preflight.json'
            with self.assertRaises(CommandError) as c:
                call_command('hr_first_delivery_check',tenant_id=1,report=str(p))
            self.assertEqual(c.exception.returncode,2)
            self.assertEqual(json.loads(p.read_text())['mode'],'READ_ONLY')
    def test_no_connection_credentials_in_report(self):
        from django.conf import settings
        result=json.dumps(collect_report(1))
        self.assertNotIn(settings.SECRET_KEY,result)
        self.assertNotIn('test-only-Strong',result)

    def test_mariadb_is_not_mysql_just_because_backend_name_matches(self):
        from hr_onboarding.management.commands.hr_first_delivery_check import mysql_version_matches_release
        self.assertFalse(mysql_version_matches_release('10.11.0-MariaDB'))
        self.assertFalse(mysql_version_matches_release('8.0.36'))
        self.assertTrue(mysql_version_matches_release('8.4.6'))
