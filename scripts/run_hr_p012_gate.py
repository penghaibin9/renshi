#!/usr/bin/env python3
"""Only P0/P1/P2. Default diagnoses; --execute provisions a fresh LOCAL QA stack.

This reuses the original production Dockerfile/lock/Compose/release command.
Never reads the deployment .env; never changes school/payroll/business data in
an existing deployment. It does NOT run the P3 import or P4 personnel journey.
Even a successful runtime gate ends TECHNICAL_GATES_PASSED_PENDING_ACCEPTANCE, not release-ready.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import time

from run_hr_acceptance_gate import (ROOT, MIN_COMPOSE, RuntimePaths, AcceptanceGateError,
    _build_runtime_env, _write_env, _compose_base, _version_tuple,
    isolated_child_env, assert_local_docker, assert_unused_project)
from probe_hr_p012_environment import host_report, write_report

APP_SERVICES = ('release','web','hr05-outbox-worker','hr05-import-worker',
    'hr18-submission-worker','hr18-exchange-worker','legacy-scheduler',
    'employee-scheduler','backup-scheduler')
PHASES = ('compose-config','image-build','infrastructure','release',
    'dependency-consistency','django-check','migration-drift','migration-applied',
    'runtime-facts','mysql-test-grant','p1-mysql','web-start','ready-http')
NOT_VERIFIED = ('NATIVE_BROWSER_LOGIN_MFA_SMTP','FULL_NAVIGATION_STATIC','SCOPE_PRIVATE_FILES',
                'POPULATED_DB_UPGRADE_REHEARSAL','WINDOWS','CLIENT_SIGNOFF')


def validate_config(config, paths, values):
    """Validate actual Compose output, not our intention to isolate it."""
    services=config.get('services',{})
    for name in APP_SERVICES:
        item=services.get(name)
        if not item or item.get('image')!=values['HR_ACCEPTANCE_IMAGE']:
            raise AcceptanceGateError('application image is not acceptance-only: '+name)
        env=item.get('environment',{})
        for key in ('DATABASE_URL','REDIS_URL','SECRET_KEY','EMAIL_HOST','FIELD_ENCRYPTION_KEYS'):
            if env.get(key)!=values[key]:
                raise AcceptanceGateError('unexpected inherited environment: '+name+'/'+key)
        if env.get('DJANGO_SETTINGS_MODULE','horilla.settings')!='horilla.settings':
            raise AcceptanceGateError('test settings are forbidden in runtime gate')
        if env.get('COMPANY_SCOPED_PERMISSIONS')!='True' or env.get('TENANT_FAIL_CLOSED')!='True':
            raise AcceptanceGateError('production authorization switches must stay on')
    for name,item in services.items():
        if item.get('container_name') or item.get('network_mode')=='host' or item.get('privileged'):
            raise AcceptanceGateError('non-isolated container configuration: '+name)
        if item.get('ports'):
            raise AcceptanceGateError('P012 automatic gate must not publish host ports: '+name)
        for mount in item.get('volumes',[]):
            if mount.get('type')!='bind':
                continue
            path=Path(mount['source']).resolve()
            # Original nginx config is code and read-only. All writable state
            # and any other bind mount must be inside this unique QA directory.
            if path==ROOT/'deploy/docker/nginx.conf' and mount.get('read_only'):
                continue
            if not path.is_relative_to(paths.root.resolve()):
                raise AcceptanceGateError('bind mount escaped the isolated QA directory')
    for section in ('volumes','networks'):
        for value in config.get(section,{}).values():
            if value.get('external'):
                raise AcceptanceGateError('external '+section+' forbidden')
    db=services.get('db',{})
    if not str(db.get('image','')).startswith('mysql:8.4@sha256:'):
        raise AcceptanceGateError('the original pinned MySQL8.4 image is required')
    denv=db.get('environment',{})
    for key in ('MYSQL_PASSWORD','MYSQL_ROOT_PASSWORD'):
        if denv.get(key)!=values[key]:
            raise AcceptanceGateError('unexpected database credential origin')


def redacted(text, values):
    for key,value in values.items():
        if any(x in key for x in ('PASSWORD','SECRET','TOKEN','KEY','DATABASE_URL','REDIS_URL')) and len(value)>=8:
            text=text.replace(value,'<redacted>')
    text=re.sub(r'([a-zA-Z][a-zA-Z0-9+.-]*://)[^\s/@]+:[^\s/@]+@',r'\1<redacted>@',text)
    return text


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true',help='create a new local QA stack, never an existing stack')
    parser.add_argument('--keep',action='store_true',help='retain only this new stack for diagnosis; output remains private')
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    parser.add_argument('--report',type=Path,default=ROOT/'.runtime'/'p012-evidence'/(stamp+'-'+secrets.token_hex(6)+'.json'))
    args=parser.parse_args(argv)
    if args.report.suffix.lower()!='.json':
        parser.error('--report must be a new .json file, never a deployment configuration')
    if args.report.exists():
        parser.error('--report already exists; preserve old evidence and choose a new path')
    report={'schema':'yueke.p012.gate.1','scope':['P0','P1','P2'],'started_at':datetime.now(timezone.utc).isoformat(),
        'status':'BLOCKED','release_approved':False,'mode':'EXECUTE_ISOLATED' if args.execute else 'READ_ONLY_DIAGNOSE',
        'host':host_report(),'phases':[{'id':p,'status':'NOT_EXECUTED'} for p in PHASES],
        'remaining':[{'id':p,'status':'NOT_VERIFIED'} for p in NOT_VERIFIED],
        'out_of_scope':['P3','P4','P5','P6','P7']}
    args.report.parent.mkdir(parents=True,exist_ok=True)
    paths=None; values={}; compose=[]; child_env={}; owns=False; exit_code=2
    def save():
        report['finished_at']=datetime.now(timezone.utc).isoformat()
        write_report(args.report, report)
    def phase(name,command,timeout=1200):
        row=next(x for x in report['phases'] if x['id']==name)
        start=time.monotonic(); row['status']='RUNNING';save()
        try:
            proc=subprocess.run(command,cwd=ROOT,env=child_env,capture_output=True,text=True,timeout=timeout)
        except Exception as exc:
            row.update(status='BLOCKED',error=type(exc).__name__);save();raise
        row.update(seconds=round(time.monotonic()-start,3),exit_code=proc.returncode,
                   status='PASS' if proc.returncode==0 else 'BLOCKED')
        # Compose config expands passwords: validate it only in memory, never log.
        if name!='compose-config':
            log=args.report.parent/(args.report.stem+'-'+name+'.log')
            fd=os.open(log, os.O_WRONLY|os.O_CREAT|os.O_TRUNC, 0o600)
            if hasattr(os, "fchmod"):
                os.fchmod(fd,0o600)
            with os.fdopen(fd,'w',encoding='utf-8') as stream:
                stream.write(redacted(proc.stdout+'\n'+proc.stderr,values))
            row['log']=log.name
        save()
        if proc.returncode:
            raise AcceptanceGateError('phase failed: '+name)
        return proc
    try:
        if not args.execute:
            report['status']='DIAGNOSED_NOT_EXECUTED' if report['host']['docker_cli'] else 'BLOCKED'
            report['blocker']='Docker CLI unavailable' if not report['host']['docker_cli'] else 'No runtime command was executed'
            exit_code=2 if report['status']=='BLOCKED' else 3
            return exit_code
        if not report['host']['docker_cli']:
            raise AcceptanceGateError('Docker CLI unavailable; no database or deployment created')
        # A fresh unguessable namespace prevents accidental reuse of live QA data.
        project='yueke_hr_p012_qa_'+secrets.token_hex(6)
        root=ROOT/'.runtime'/'p012'/project
        paths=RuntimePaths(root,root/'acceptance.env',root/'backups',args.report,root/'handover',root/'handover-audit')
        values=_build_runtime_env(paths)
        child_env=isolated_child_env(values)
        version=subprocess.run(['docker','compose','version','--short'],env=child_env,capture_output=True,text=True,check=True,timeout=20)
        if _version_tuple(version.stdout)<MIN_COMPOSE:
            raise AcceptanceGateError('Compose2.24.4+ is required')
        assert_local_docker(child_env)
        assert_unused_project(project,child_env)
        root.mkdir(parents=True,exist_ok=False);os.chmod(root,0o700)
        for path in (paths.backup_root,paths.handover_root,paths.handover_audit_root):
            path.mkdir()
        _write_env(paths.env_file,values)
        compose=_compose_base(project,paths.env_file)
        report['project']=project
        config=phase('compose-config',[*compose,'config','--format','json'],60)
        try:
            validate_config(json.loads(config.stdout),paths,values)
        except Exception:
            next(x for x in report['phases'] if x['id']=='compose-config')['status']='BLOCKED'
            raise
        owns=True
        phase('image-build',[*compose,'build','release'],1800)
        phase('infrastructure',[*compose,'up','-d','--wait','db','redis','clamav'],1200)
        phase('release',[*compose,'run','--rm','--no-deps','release'],1200)
        prefix=[*compose,'run','--rm','--no-deps','web']
        phase('dependency-consistency',[*prefix,'python','-c',
            'import importlib.metadata as m; from scripts.probe_hr_p012_environment import inventory; r=inventory(); import json; print(json.dumps(r)); assert r["missing_count"]==r["mismatch_count"]==0'])
        phase('django-check',[*prefix,'python','manage.py','check','--deploy','--fail-level','WARNING'])
        phase('migration-drift',[*prefix,'python','manage.py','makemigrations','--check','--dry-run'])
        phase('migration-applied',[*prefix,'python','manage.py','migrate','--check'])
        phase('runtime-facts',[*prefix,'python','scripts/probe_hr_p012_environment.py','--runtime'])
        # Only a newly isolated server. The existing app user remains unchanged
        # on renshi_db; temporary test-schema grant cannot target a live server.
        phase('mysql-test-grant',[*compose,'exec','-T','db','sh','-lc',
            'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot --execute="GRANT ALL PRIVILEGES ON test_renshi_db.* TO \'renshi_user\'@\'%\';"'])
        phase('p1-mysql',[*prefix,'python','manage.py','test',
            'hr_onboarding.tests.test_p012_mysql_runtime','--noinput','--verbosity','2'])
        phase('web-start',[*compose,'up','-d','--wait','--no-deps','web'],300)
        phase('ready-http',[*compose,'exec','-T','web','python','-c',
            "import urllib.request; r=urllib.request.Request('http://127.0.0.1:8000/ready/',headers={'Host':'acceptance.local','X-Forwarded-Proto':'https'}); x=urllib.request.urlopen(r,timeout=15); assert x.status==200; print('INTERNAL_READY_HTTP_200; NOT_TLS_BROWSER_EVIDENCE')"],30)
        report['status']='TECHNICAL_GATES_PASSED_PENDING_ACCEPTANCE'
        # The automated infrastructure proof deliberately cannot approve P2's
        # remaining native login/MFA/private-file/browser gates or P3-P7.
        exit_code=3
    except Exception as exc:
        report['status']='BLOCKED';report['blocker']=redacted(str(exc),values)
        exit_code=2
    finally:
        if owns and not args.keep:
            try:
                cleaned=subprocess.run([*compose,'down','-v','--remove-orphans'],cwd=ROOT,env=child_env,
                    text=True,capture_output=True,timeout=180)
                report['cleanup']='PASS' if cleaned.returncode==0 else 'BLOCKED'
                if cleaned.returncode:
                    report['status']='BLOCKED'
            except Exception:
                report['cleanup']='BLOCKED';report['status']='BLOCKED';report['blocker']='Isolated cleanup failed; resources require manual inspection'
        elif owns:
            report['cleanup']='KEPT_BY_REQUEST'
        else:
            report['cleanup']='NO_RESOURCE_OWNERSHIP_NO_DOWN_CALLED'
        if paths and (not owns or report.get('cleanup')=='PASS'):
            shutil.rmtree(paths.root,ignore_errors=True)
        if report['status']=='BLOCKED':
            exit_code=2
        save()
        print('P012 '+report['status']+' | report='+str(args.report))
    return exit_code

if __name__=='__main__':
    raise SystemExit(main())
