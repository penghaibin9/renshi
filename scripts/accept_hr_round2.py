#!/usr/bin/env python3
"""Non-destructive preflight; --run mutates ONLY an explicitly confirmed QA DB.
No dependency installation, GitHub, production deploy, sample-data flush or
permission auto-grant. Passing this script is not production release approval.
"""
import argparse
import datetime as dt
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
FOCUSED=["hr_exit.tests.test_round2_flex_workflow", "hr_self.tests.test_round2_commands",
         "hr_data.tests.test_round2_retirement_and_operations"]
DOMAINS=["base","hr_control_center","hr_structure","hr_staff","hr_recruitment","hr_onboarding",
 "hr_changes","hr_contracts","hr_external","hr_qualification","hr10_development","hr_time",
 "hr_assessment","hr_title","hr_appointment","hr_payroll","hr_exit","hr_self","hr_data"]
MANUAL=["四角色与双学校真实浏览器流程/越权验收", "多进程并发、幂等和上传中切学校验收",
        "备份恢复、迁移升级演练、容量与安全扫描", "真实短信/邮件/杀毒/签章/IAM/财税等适用外部系统验收"]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run",action="store_true",help="Run migrations and tests on confirmed disposable MySQL only")
    parser.add_argument("--confirm-disposable-database",default="")
    parser.add_argument("--output",default=str(ROOT/".local"/"round2-acceptance"))
    args=parser.parse_args()
    output=Path(args.output)/dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output.mkdir(parents=True,exist_ok=True)
    result={"automaticGate":"BLOCKED","productionRelease":"NOT_RELEASED","pendingProductionGates":MANUAL,
            "steps":[],"runtime":sys.version.split()[0]}
    def finish(code,message):
        result["message"]=message
        (output/"result.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
        print(json.dumps(result,ensure_ascii=False,indent=2));print("Evidence:",output)
        return code
    missing=[name for name in ("django","rest_framework","MySQLdb") if importlib.util.find_spec(name) is None]
    if missing:
        return finish(2,"Missing locked runtime dependencies: "+", ".join(missing)+". No database or source changed.")
    sys.path.insert(0,str(ROOT/"backend"));os.environ.setdefault("DJANGO_SETTINGS_MODULE","horilla.settings")
    try:
        import django
        from django.conf import settings
        from django.db import connections
        if set(settings.DATABASES)!={"default"}:
            return finish(2,"This gate requires an explicitly isolated single-DB test configuration; review other aliases separately.")
        connection=connections["default"]
        config=connection.settings_dict
        name=str(config.get("NAME") or "")
        test_name=str((config.get("TEST") or {}).get("NAME") or ("test_"+name))
        if connection.vendor!="mysql":return finish(2,"MySQL-only: unsupported database engine; never substitute SQLite.")
        if not re.fullmatch(r"(?:qa_|test_|acceptance_)[A-Za-z0-9_]+",name):
            return finish(2,"Refusing non-QA database name. Use a separate qa_/test_/acceptance_ database.")
        if test_name==name or not re.fullmatch(r"(?:qa_|test_|acceptance_)[A-Za-z0-9_]+",test_name):
            return finish(2,"Refusing unsafe Django TEST.NAME: use a different disposable test database.")
        if (config.get("TEST") or {}).get("MIRROR"):
            return finish(2,"Refusing a mirrored test database.")
        result["databaseName"]=name;result["djangoTestDatabaseName"]=test_name
        if not args.run:return finish(2,"Preflight only. No SQL migration/test executed. Supply --run and the exact disposable QA DB confirmation.")
        if args.confirm_disposable_database!=name:
            return finish(2,"Database confirmation does not match. No migration or tests executed.")
        django.setup()
        connection.ensure_connection()
        with connection.cursor() as cursor:
            cursor.execute("SELECT VERSION()")
            server_version=str(cursor.fetchone()[0])
        result["mysqlVersion"]=server_version
        if "mariadb" in server_version.lower() or not server_version.startswith("8.4."):
            return finish(2,"Release baseline is MySQL 8.4; no MariaDB/other-version substitution in this gate.")
        connection.close()
    except Exception as exc:
        # Avoid printing connection strings, settings, passwords or tokens.
        return finish(2,"Runtime/database preflight failed: "+type(exc).__name__+". Inspect local configuration without sharing secrets.")
    commands=[
      [sys.executable,"-m","pip","check"],
      [sys.executable,"manage.py","check"],
      [sys.executable,"manage.py","makemigrations","--check","--dry-run"],
      [sys.executable,"manage.py","migrate","--noinput"],
      [sys.executable,"manage.py","migrate","--check"],
      [sys.executable,"manage.py","test",*FOCUSED,"--noinput","--verbosity","2"],
      [sys.executable,"manage.py","test",*DOMAINS,"--noinput","--verbosity","1"],
      [sys.executable,"manage.py","check","--deploy","--fail-level","WARNING"],
    ]
    for index,command in enumerate(commands,1):
        print("Running gate",index,flush=True)
        with (output/f"{index:02d}.log").open("w",encoding="utf-8") as log:
            process=subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=False)
        result["steps"].append({"step":index,"command":command[1:],"returnCode":process.returncode,"log":f"{index:02d}.log"})
        if process.returncode:return finish(1,f"Automatic gate stopped at step {index}; failure preserved, later stages not run.")
    result["automaticGate"]="PASSED"
    return finish(0,"Automated subset passed on confirmed QA MySQL. Production remains NOT_RELEASED until the listed independent acceptance gates pass.")
if __name__=="__main__":raise SystemExit(main())
