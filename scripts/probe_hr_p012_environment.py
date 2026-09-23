#!/usr/bin/env python3
"""P2 read-only host/runtime inventory. No install, DB writes, or secret output.

Host packages are NOT evidence about the Docker image. --runtime must execute
inside the built image with the original settings and an isolated MySQL schema.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.metadata as metadata
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def locked_dependencies(path: Path) -> list[tuple[str, str]]:
    rows = []
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        match = re.fullmatch(r'([A-Za-z0-9_.-]+)==([^\s;]+)', line)
        if not match:
            raise ValueError('unsupported dependency lock entry; do not silently skip it')
        rows.append(match.groups())
    return rows


def inventory(root: Path = ROOT, version_reader=metadata.version) -> dict:
    rows = []
    for name, expected in locked_dependencies(root / 'requirements.lock'):
        try:
            actual = version_reader(name)
        except metadata.PackageNotFoundError:
            actual = None
        rows.append({'package': name, 'expected': expected, 'installed': actual,
                     'status': 'MATCH' if actual == expected else 'MISSING' if actual is None else 'MISMATCH'})
    return {'python': platform.python_version(), 'platform': platform.system(),
            'lock_sha256': hashlib.sha256((root/'requirements.lock').read_bytes()).hexdigest(),
            'count': len(rows), 'dependencies': rows,
            'missing_count': sum(x['status'] == 'MISSING' for x in rows),
            'mismatch_count': sum(x['status'] == 'MISMATCH' for x in rows)}


def host_report() -> dict:
    result = inventory()
    result.update(schema='yueke.p012.host.1', mode='READ_ONLY', location='HOST_NOT_PRODUCTION_IMAGE',
                  docker_cli=bool(shutil.which('docker')), mysql_server=bool(shutil.which('mysqld')),
                  mysql_driver=bool(importlib.util.find_spec('MySQLdb')), release_approved=False)
    # Docker packages are the authority for a Docker release, not the host Python.
    result['status'] = 'HOST_TOOLS_AVAILABLE' if result['docker_cli'] else 'BLOCKED'
    result['note'] = '宿主依赖清单不能作为容器安装结果；不安装、不修改环境、不连接用户生产。'
    return result


def runtime_report() -> dict:
    result = inventory()
    result.update(schema='yueke.p012.runtime.1', mode='READ_ONLY', location='APPLICATION_RUNTIME',
                  release_approved=False, status='BLOCKED',
                  not_verified=['实际浏览器账号登录/MFA/完整导航','院系/本人/跨校权限及私有文件','客户验收','P3–P7'])
    checks = result['checks'] = []
    def add(code, passed, detail):
        checks.append({'id':code,'status':'PASS' if passed else 'BLOCKED','detail':detail})
    add('PYTHON_RELEASE', sys.version_info[:2] == (3,12), '与原Dockerfile Python3.12发布线一致')
    add('DEPENDENCY_LOCK', not result['missing_count'] and not result['mismatch_count'],
        '逐项核对原锁文件，没有临时放宽版本')
    settings_name = os.environ.get('DJANGO_SETTINGS_MODULE','horilla.settings')
    add('SETTINGS_ENTRY', settings_name == 'horilla.settings', '必须使用原完整设置')
    if settings_name != 'horilla.settings':
        return result
    os.environ.setdefault('DJANGO_SETTINGS_MODULE','horilla.settings')
    sys.path.insert(0,str(ROOT/'backend'))
    try:
        import django
        django.setup()
        from django.conf import settings
        from django.db import connection
        from django.db.migrations.executor import MigrationExecutor
        add('ORIGINAL_URLCONF',settings.ROOT_URLCONF == 'horilla.urls','实际加载原全局路由')
        add('NO_MIGRATION_REPLACEMENT',not getattr(settings,'MIGRATION_MODULES',{}),'不替换/跳过历史迁移')
        add('PRODUCTION_AUTH',not settings.DEBUG and getattr(settings,'COMPANY_SCOPED_PERMISSIONS',False)
            and getattr(settings,'TENANT_FAIL_CLOSED',False),'保持生产模式和学校权限')
        add('MYSQL_VENDOR',connection.vendor == 'mysql','不是SQLite/MariaDB替代验收')
        if connection.vendor != 'mysql':
            return result
        connection.ensure_connection()
        with connection.cursor() as cursor:
            cursor.execute('SELECT VERSION(), @@sql_mode, @@foreign_key_checks, @@transaction_isolation')
            version, mode, fk, isolation = cursor.fetchone()
            result['database']={'version':str(version),'sql_mode':str(mode),'foreign_keys':int(fk),'isolation':str(isolation)}
            add('MYSQL_RELEASE',str(version).startswith('8.4.') and 'mariadb' not in str(version).lower(),'原8.4发布线')
            add('STRICT_MODE',bool({'STRICT_TRANS_TABLES','STRICT_ALL_TABLES'} & set(str(mode).split(','))),'严格数据模式')
            add('FOREIGN_KEYS',fk == 1,'当前会话外键检查')
            cursor.execute("SELECT COUNT(*),COALESCE(SUM(ENGINE <> 'InnoDB'),0) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_type='BASE TABLE'")
            total,other=cursor.fetchone()
            result['table_count']=int(total)
            add('INNODB_TABLES',bool(total) and not other,'实际表引擎；非InnoDB数量：'+str(other))
            cursor.execute('SELECT TRIGGER_NAME FROM information_schema.triggers WHERE TRIGGER_SCHEMA=DATABASE()')
            triggers={x[0] for x in cursor.fetchall()}
            import importlib
            critical=importlib.import_module('hr_staff.migrations.0021_self_submission_seals').TRIGGERS
            add('CRITICAL_SEALS',set(critical).issubset(triggers),'HR03关键防篡改触发器存在性；不能代替行为测试')
            result['critical_seals']={'expected':len(critical),'present':len(set(critical)&triggers)}
        executor=MigrationExecutor(connection)
        executor.loader.check_consistent_history(connection)
        pending=executor.migration_plan(executor.loader.graph.leaf_nodes())
        add('MIGRATIONS',not pending and not executor.loader.detect_conflicts(),'原完整迁移图实际应用')
        result['migration_count']=len(executor.loader.applied_migrations)
        result['migration_heads']=[list(x) for x in executor.loader.graph.leaf_nodes()]
    except Exception as exc:
        # Error type is useful; str(exc) can include DB credentials/SQL payloads.
        add('RUNTIME_INITIALIZATION',False,type(exc).__name__+'；检查隔离日志，报告不输出连接串或人员内容')
    result['status']='TECHNICAL_CHECKS_PASSED' if checks and all(x['status']=='PASS' for x in checks) else 'BLOCKED'
    result['not_verified']=['实际浏览器账号登录/MFA/完整导航','院系/本人/跨校权限及私有文件','客户验收','P3–P7']
    return result


def write_report(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".p012-report-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime',action='store_true')
    parser.add_argument('--report',type=Path)
    args=parser.parse_args(argv)
    report=runtime_report() if args.runtime else host_report()
    text=json.dumps(report,ensure_ascii=False,indent=2)+'\n'
    if args.report:
        write_report(args.report, report)
    print(text)
    return 2 if report['status']=='BLOCKED' else 0

if __name__=='__main__':
    raise SystemExit(main())
