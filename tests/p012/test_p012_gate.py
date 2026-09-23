"""Local safety unit tests. Mocked Docker JSON is NOT real Compose/MySQL proof."""
import copy
import importlib.metadata as metadata
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
import run_hr_acceptance_gate as shared
import run_hr_p012_gate as gate
import probe_hr_p012_environment as probe

class P012GateSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        r=Path(self.temp.name)
        self.paths=shared.RuntimePaths(r,r/'acceptance.env',r/'backups',r/'out.json')
        self.values=shared._build_runtime_env(self.paths)
    def config(self):
        services={name:{'image':self.values['HR_ACCEPTANCE_IMAGE'],'environment':dict(self.values)} for name in gate.APP_SERVICES}
        services['db']={'image':'mysql:8.4@sha256:'+('a'*64),'environment':dict(self.values)}
        return {'services':services,'volumes':{'data':{}},'networks':{'default':{}}}
    def test_same_host_env_never_overrides_generated_db(self):
        with patch.dict(os.environ,{'DATABASE_URL':'mysql://production','COMPOSE_FILE':'production.yml',
            'DJANGO_SETTINGS_MODULE':'fake.settings','DOCKER_HOST':'ssh://remote','EMAIL_HOST':'real-mail','PYTHONPATH':'/fake'}):
            env=shared.isolated_child_env(self.values)
        self.assertEqual(env['DATABASE_URL'],self.values['DATABASE_URL'])
        for k in ('COMPOSE_FILE','DJANGO_SETTINGS_MODULE','DOCKER_HOST','PYTHONPATH'):
            self.assertNotIn(k,env)
        self.assertEqual(env['COMPOSE_DISABLE_ENV_FILE'],'1')
    def test_each_generation_has_a_distinct_image(self):
        other=shared._build_runtime_env(self.paths)
        self.assertNotEqual(other['HR_ACCEPTANCE_IMAGE'],self.values['HR_ACCEPTANCE_IMAGE'])
        self.assertNotIn('renshi-web',self.values['HR_ACCEPTANCE_IMAGE'])
    def test_generated_env_is_private_and_not_overwritten(self):
        shared._write_env(self.paths.env_file,self.values)
        self.assertEqual(self.paths.env_file.stat().st_mode & 0o777,0o600)
        with self.assertRaises(FileExistsError): shared._write_env(self.paths.env_file,self.values)
    def test_newline_never_writes_file(self):
        with self.assertRaises(shared.AcceptanceGateError): shared._write_env(self.paths.env_file,{'SECRET_KEY':'a\nb'})
        self.assertFalse(self.paths.env_file.exists())
    def test_remote_docker_is_refused(self):
        output=json.dumps([{'Endpoints':{'docker':{'Host':'ssh://remote.example'}}}])
        with patch.object(shared,'_run',return_value=subprocess.CompletedProcess([],0,output,'')):
            with self.assertRaises(shared.AcceptanceGateError): shared.assert_local_docker({})
    def test_local_socket_is_accepted(self):
        output=json.dumps([{'Endpoints':{'docker':{'Host':'unix:///var/run/docker.sock'}}}])
        with patch.object(shared,'_run',return_value=subprocess.CompletedProcess([],0,output,'')):
            shared.assert_local_docker({})
    def test_existing_resources_are_not_adopted(self):
        with patch.object(shared,'_run',return_value=subprocess.CompletedProcess([],0,'resource-id','')):
            with self.assertRaises(shared.AcceptanceGateError): shared.assert_unused_project('qa_example',{})
    def test_all_three_resource_types_checked(self):
        with patch.object(shared,'_run',return_value=subprocess.CompletedProcess([],0,'','')) as run:
            shared.assert_unused_project('qa_example',{})
        self.assertEqual(run.call_count,3)
    def test_config_accepts_isolated_expected_values(self):
        gate.validate_config(self.config(),self.paths,self.values)
    def test_config_missing_hr05_worker_is_refused(self):
        conf=self.config();conf['services'].pop('hr05-import-worker')
        with self.assertRaises(shared.AcceptanceGateError):gate.validate_config(conf,self.paths,self.values)
    def test_shared_production_image_is_refused(self):
        conf=self.config();conf['services']['web']['image']='renshi-web:latest'
        with self.assertRaises(shared.AcceptanceGateError):gate.validate_config(conf,self.paths,self.values)
    def test_foreign_database_value_is_refused(self):
        conf=self.config();conf['services']['hr05-outbox-worker']['environment']['DATABASE_URL']='mysql://foreign'
        with self.assertRaises(shared.AcceptanceGateError):gate.validate_config(conf,self.paths,self.values)
    def test_scope_disabled_is_refused(self):
        conf=self.config();conf['services']['web']['environment']['COMPANY_SCOPED_PERMISSIONS']='False'
        with self.assertRaises(shared.AcceptanceGateError):gate.validate_config(conf,self.paths,self.values)
    def test_test_settings_are_refused(self):
        conf=self.config();conf['services']['web']['environment']['DJANGO_SETTINGS_MODULE']='hr_onboarding.tests.sqlite_settings'
        with self.assertRaises(shared.AcceptanceGateError):gate.validate_config(conf,self.paths,self.values)
    def test_host_port_is_refused(self):
        conf=self.config();conf['services']['nginx']={'ports':[{'published':'80','target':80}]}
        with self.assertRaises(shared.AcceptanceGateError):gate.validate_config(conf,self.paths,self.values)
    def test_host_volume_is_refused(self):
        conf=self.config();conf['services']['web']['volumes']=[{'type':'bind','source':'/var/production'}]
        with self.assertRaises(shared.AcceptanceGateError):gate.validate_config(conf,self.paths,self.values)
    def test_external_volume_is_refused(self):
        conf=self.config();conf['volumes']['data']={'external':True}
        with self.assertRaises(shared.AcceptanceGateError):gate.validate_config(conf,self.paths,self.values)
    def test_unpinned_or_other_mysql_line_is_refused(self):
        for value in ('mysql:8.4','mysql:8.0@sha256:a','mariadb:11'):
            conf=self.config();conf['services']['db']['image']=value
            with self.assertRaises(shared.AcceptanceGateError):gate.validate_config(conf,self.paths,self.values)
    def test_all_app_services_have_overlay_env_and_image(self):
        # Parsing text here checks coverage; real Compose merge remains a runtime gate.
        text=(ROOT/'docker-compose.acceptance.yml').read_text()
        for name in gate.APP_SERVICES:
            block=re.split(r'\n  (?=\S)',text.split('  '+name+':\n',1)[1],maxsplit=1)[0]
            self.assertIn('HR_ACCEPTANCE_IMAGE',block)
            self.assertIn('HR_ACCEPTANCE_ENV_FILE',block)
    def test_automatic_scope_does_not_include_p3_to_p7_commands(self):
        self.assertNotIn('backup-restore',gate.PHASES)
        text=(ROOT/'scripts/run_hr_p012_gate.py').read_text()
        self.assertNotIn('bootstrap_first_school',text)
        self.assertIn("'P3','P4','P5','P6','P7'",text)
    def test_redaction_removes_generated_credentials(self):
        values=self.values
        sample=values['DATABASE_URL']+'\n'+values['SECRET_KEY']+'\n'+values['FIELD_ENCRYPTION_KEYS']
        cleaned=gate.redacted(sample,values)
        self.assertNotIn(values['MYSQL_PASSWORD'],cleaned)
        self.assertNotIn(values['SECRET_KEY'],cleaned)
        self.assertNotIn(values['FIELD_ENCRYPTION_KEYS'],cleaned)
    def test_blocked_host_calls_no_docker_and_no_cleanup(self):
        with patch.object(gate,'host_report',return_value={'docker_cli':False,'status':'BLOCKED'}),patch.object(gate.subprocess,'run') as run:
            code=gate.main(['--execute','--report',str(self.paths.evidence_file)])
        self.assertEqual(code,2);run.assert_not_called()
        report=json.loads(self.paths.evidence_file.read_text())
        self.assertFalse(report['release_approved'])
        self.assertTrue(all(x['status']=='NOT_EXECUTED' for x in report['phases']))
        self.assertEqual(report['cleanup'],'NO_RESOURCE_OWNERSHIP_NO_DOWN_CALLED')
    def test_default_is_diagnosis_not_execution(self):
        with patch.object(gate,'host_report',return_value={'docker_cli':True}),patch.object(gate.subprocess,'run') as run:
            code=gate.main(['--report',str(self.paths.evidence_file)])
        self.assertEqual(code,3);run.assert_not_called()
    def test_lock_parser_fails_on_unpinned_entry(self):
        path=Path(self.temp.name)/'requirements.lock';path.write_text('Django>=5\n')
        with self.assertRaises(ValueError):probe.locked_dependencies(path)
    def test_dependency_inventory_tracks_missing_and_mismatch(self):
        path=Path(self.temp.name)/'requirements.lock';path.write_text('Django==5.2.17\nfoo==1.0\nbar==2.0\n')
        def version(name):
            if name=='foo':raise metadata.PackageNotFoundError(name)
            return {'Django':'5.2.17','bar':'1.0'}[name]
        result=probe.inventory(Path(self.temp.name),version)
        self.assertEqual(result['missing_count'],1);self.assertEqual(result['mismatch_count'],1)
    def test_runtime_refuses_test_settings_before_django_import(self):
        with patch.dict(os.environ,{'DJANGO_SETTINGS_MODULE':'fake.test.settings'}):
            result=probe.runtime_report()
        self.assertEqual(result['status'],'BLOCKED');self.assertFalse(result['release_approved'])
        self.assertFalse(any(x['id']=='MYSQL_VENDOR' for x in result['checks']))
    def test_diagnostic_report_cannot_overwrite_dotenv(self):
        report=self.paths.root/'.env'
        report.write_text('DEPLOYMENT=DO_NOT_TOUCH')
        with self.assertRaises(SystemExit):gate.main(['--report',str(report)])
        self.assertEqual(report.read_text(),'DEPLOYMENT=DO_NOT_TOUCH')
    def test_existing_evidence_is_not_overwritten(self):
        self.paths.evidence_file.write_text('prior evidence')
        with self.assertRaises(SystemExit):gate.main(['--report',str(self.paths.evidence_file)])
        self.assertEqual(self.paths.evidence_file.read_text(),'prior evidence')
    def test_gate_command_not_allowed_to_adopt_existing_project(self):
        # No --project or env-file override: new gate always generates its own namespace.
        with self.assertRaises(SystemExit):gate.main(['--project','my-production'])
    def test_cleanup_failure_has_blocked_status_and_exit_two(self):
        # Every Docker result below is an explicit unit fixture, not live evidence.
        root=self.paths.root/'code';root.mkdir()
        config=self.config()
        def completed(command, **kwargs):
            if command[1:4]==['compose','version','--short']:
                return subprocess.CompletedProcess(command,0,'2.24.4','')
            if '--format' in command:
                return subprocess.CompletedProcess(command,0,json.dumps(config),'')
            if 'down' in command:
                return subprocess.CompletedProcess(command,1,'','simulated cleanup failure')
            return subprocess.CompletedProcess(command,0,'UNIT_FIXTURE_NOT_RUNTIME_PROOF','')
        with patch.object(gate,'ROOT',root),patch.object(gate,'host_report',return_value={'docker_cli':True}),\
             patch.object(gate,'_build_runtime_env',return_value=self.values),\
             patch.object(gate,'assert_local_docker'),patch.object(gate,'assert_unused_project'),\
             patch.object(gate.subprocess,'run',side_effect=completed):
            code=gate.main(['--execute','--report',str(self.paths.evidence_file)])
        report=json.loads(self.paths.evidence_file.read_text())
        self.assertEqual(code,2);self.assertEqual(report['status'],'BLOCKED')
        self.assertEqual(report['cleanup'],'BLOCKED');self.assertFalse(report['release_approved'])
    def test_atomic_private_report(self):
        probe.write_report(self.paths.evidence_file,{'status':'BLOCKED'})
        probe.write_report(self.paths.evidence_file,{'status':'NEEDS_ACCEPTANCE'})
        self.assertEqual(self.paths.evidence_file.stat().st_mode & 0o777,0o600)
        self.assertEqual(json.loads(self.paths.evidence_file.read_text())['status'],'NEEDS_ACCEPTANCE')
        self.assertEqual(list(self.paths.root.glob('.p012-report-*')),[])

if __name__=='__main__':unittest.main(verbosity=2)
