"""Read-only first-customer technical preflight. Never migrates, seeds or pays."""
from __future__ import annotations
import json
import os
import tempfile
from pathlib import Path
from datetime import datetime, timezone
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor


def mysql_version_matches_release(version):
    # Current docker-compose.prod.yml pins MySQL 8.4. A MariaDB or a different
    # release line must not get a green check from the Django backend name alone.
    value=str(version).lower()
    return value.startswith('8.4.') and 'mariadb' not in value


def collect_report(tenant_id):
    checks = []
    def add(code, label, status, detail):
        checks.append({'id': code, 'item': label, 'status': status, 'detail': detail})
    # These are configuration checks, never substitutes for browser/role tests.
    add('CANONICAL_SETTINGS', '使用原完整Django设置入口',
        'PASS' if getattr(settings, 'SETTINGS_MODULE', '') == 'horilla.settings' else 'BLOCKED',
        '不接受mini/sqlite/ci设置冒充生产入口')
    add('CANONICAL_ROUTES', '使用原全局路由',
        'PASS' if getattr(settings, 'ROOT_URLCONF', '') == 'horilla.urls' else 'BLOCKED',
        '原生登录与完整导航仍需独立实际回放')
    required_apps = {'hr_control_center','hr_structure','hr_staff','hr_recruitment','hr_onboarding',
        'hr_changes','hr_contracts','hr_external','hr_qualification','hr10_development','hr_time',
        'hr_assessment','hr_title','hr_appointment','hr_payroll','hr_exit','hr_self','hr_data'}
    from django.apps import apps
    installed = {app.label for app in apps.get_app_configs()}
    missing = sorted(required_apps - installed)
    add('CANONICAL_HR_APPS', '18个原HR应用完整加载', 'BLOCKED' if missing else 'PASS',
        '未加载：'+','.join(missing) if missing else '完整应用注册；不等于18模块业务验收')
    add('TENANT_FAIL_CLOSED', '无学校上下文时拒绝访问',
        'PASS' if getattr(settings,'TENANT_FAIL_CLOSED',False) else 'BLOCKED', '检查原配置开关')
    cfg = settings.DATABASES.get('default', {})
    add('DB_ENGINE', '正式数据库必须为MySQL', 'PASS' if cfg.get('ENGINE') == 'django.db.backends.mysql' else 'BLOCKED',
        '不把SQLite受控测试当MySQL验收')
    add('DEBUG_OFF', '调试模式关闭', 'PASS' if not settings.DEBUG else 'BLOCKED', '只记录是否满足，不输出密钥或连接串')
    add('MIGRATION_OVERRIDES', '历史迁移不被测试设置跳过', 'BLOCKED' if getattr(settings,'MIGRATION_MODULES',{}) else 'PASS',
        'None及重定向迁移模块都会改变历史迁移图；P2只接受原正式迁移图')
    add('AUTH_BACKEND', '学校范围权限后端启用', 'PASS' if 'base.auth_backends.CompanyScopedBackend' in settings.AUTHENTICATION_BACKENDS and getattr(settings,'COMPANY_SCOPED_PERMISSIONS',False) else 'BLOCKED',
        '不能以测试身份或全局直接授权替代学校范围权限')
    middleware = list(settings.MIDDLEWARE)
    mw = set(middleware)
    ordered = ['django.contrib.sessions.middleware.SessionMiddleware',
        'django.contrib.auth.middleware.AuthenticationMiddleware',
        'platform_access.middleware.SafeCompanyMiddleware']
    order_ok = all(name in mw for name in ordered)
    if order_ok:
        indexes = [middleware.index(name) for name in ordered]
        order_ok = indexes == sorted(indexes)
    add('TENANT_MIDDLEWARE_ORDER', '会话→认证→安全学校上下文的顺序',
        'PASS' if order_ok else 'BLOCKED', '缺学校中间件或顺序错误不能只凭权限后端名称通过')
    for code, title, expected in [
        ('MFA_MIDDLEWARE','生产双因素认证','base.middleware.TwoFactorAuthMiddleware'),
        ('UPLOAD_SCAN_MIDDLEWARE','原上传扫描中间件','base.upload_security.MalwareScanMiddleware'),
        ('STATIC_MIDDLEWARE','原静态资源中间件','whitenoise.middleware.WhiteNoiseMiddleware'),
    ]:
        add(code, title, 'PASS' if expected in mw else 'BLOCKED', '配置存在，不代表网络行为已实测')
    add('MFA_ENABLED','原生产双因素开关开启',
        'PASS' if getattr(settings,'TWO_FACTORS_AUTHENTICATION',False) else 'BLOCKED', '不以关闭MFA换取登录通过')
    add('UPLOAD_SCAN_REQUIRED','原上传恶意文件检查开启',
        'PASS' if getattr(settings,'MALWARE_SCAN_REQUIRED',False) else 'BLOCKED', '扫描服务器连通与私有下载仍待独立验证')
    for code, path, title in [
        ('SESSION_MIDDLEWARE','django.contrib.sessions.middleware.SessionMiddleware','会话中间件'),
        ('AUTH_MIDDLEWARE','django.contrib.auth.middleware.AuthenticationMiddleware','身份中间件'),
        ('CSRF_MIDDLEWARE','django.middleware.csrf.CsrfViewMiddleware','CSRF中间件')]:
        add(code, title, 'PASS' if path in mw else 'BLOCKED', '不得用测试桥接替代此生产设置')
    for code, setting in [('SESSION_COOKIE','SESSION_COOKIE_SECURE'),('CSRF_COOKIE','CSRF_COOKIE_SECURE')]:
        add(code, '安全Cookie '+setting, 'PASS' if getattr(settings,setting,False) else 'BLOCKED', '正式部署须HTTPS；本报告不验证实际TLS链')
    try:
        connection.ensure_connection()
        add('DB_CONNECTION','数据库连通','PASS','实际建立连接，只读检查')
        if connection.vendor == 'mysql':
            with connection.cursor() as c:
                c.execute('SELECT VERSION(), @@transaction_isolation, @@sql_mode, @@foreign_key_checks, @@default_storage_engine')
                version,isolation,mode,foreign_keys,storage_engine = c.fetchone()
            add('DB_VERSION','数据库版本与项目8.4发布线一致','PASS' if mysql_version_matches_release(version) else 'BLOCKED',str(version))
            add('DB_STRICT','严格数据模式','PASS' if 'STRICT_TRANS_TABLES' in mode or 'STRICT_ALL_TABLES' in mode else 'BLOCKED', '事务隔离：'+str(isolation))
            add('DB_FOREIGN_KEYS','当前连接外键检查开启', 'PASS' if foreign_keys == 1 else 'BLOCKED', '不允许关闭外键换取迁移通过')
            add('DB_STORAGE_DEFAULT','默认事务存储引擎', 'PASS' if str(storage_engine).upper() == 'INNODB' else 'BLOCKED', str(storage_engine))
            with connection.cursor() as c:
                c.execute("SELECT COUNT(*), COALESCE(SUM(ENGINE <> 'InnoDB'),0) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_type='BASE TABLE'")
                total_tables, other_engines = c.fetchone()
            add('DB_TABLE_ENGINES','实际业务表使用InnoDB',
                'PASS' if total_tables and not other_engines else 'BLOCKED',
                f'当前库表数：{total_tables}；非InnoDB表：{other_engines}')
        executor=MigrationExecutor(connection)
        executor.loader.check_consistent_history(connection)
        pending=executor.migration_plan(executor.loader.graph.leaf_nodes())
        add('MIGRATION_STATE','迁移应用状态','BLOCKED' if pending else 'PASS',f'待应用迁移数：{len(pending)}；未自动执行迁移')
        conflicts = executor.loader.detect_conflicts()
        add('MIGRATION_GRAPH', '迁移图无分叉与缺失依赖', 'BLOCKED' if conflicts else 'PASS',
            f'分叉应用数：{len(conflicts)}；历史一致性已检查')
        try:
            Company = apps.get_model('base','Company')
            valid_school = Company.objects.filter(pk=tenant_id, is_active=True).exists()
            add('SCHOOL_EXISTS','核对真实有效学校', 'PASS' if valid_school else 'BLOCKED',
                '只确认ID对应有效学校，不输出学校名称或人员数据')
        except Exception as exc:
            add('SCHOOL_EXISTS','核对真实有效学校','BLOCKED',type(exc).__name__+'；学校模型或查询未能验证')
        from hr_onboarding.models import HrOnboardingTemplateVersion
        from hr_onboarding.services.school_template_service import SCHEMA, verify_school_template
        versions=HrOnboardingTemplateVersion.objects.filter(tenant_id=tenant_id,status='ACTIVE').select_related('template')
        managed=0; invalid=0
        for v in versions.iterator():
            if (v.snapshot_json or {}).get('schema') == SCHEMA:
                managed += 1
                try: verify_school_template(v,tenant_id)
                except Exception: invalid += 1
        add('SCHOOL_PLANS','本校已发布方案完整性','BLOCKED' if invalid else 'PASS' if managed else 'NOT_VERIFIED',
            f'新校本版本：{managed}；完整性失败：{invalid}；未读取或输出个人材料')
    except Exception as exc:
        add('DB_INSPECTION','数据库只读检查','BLOCKED',type(exc).__name__+'；检查运行日志定位，报告不输出凭证')
    for code,title in [
        ('LOCK_RUNTIME','MySQL真实锁竞争与失败回滚'),('PRIVATE_FILES','实际私有文件上传/越权下载'),
        ('REAL_LOGIN','实际账号/密码或SSO与完整导航'),('SCOPE_MATRIX','校级/院系/本人/跨校权限与文件导出'),
        ('CORE_JOURNEY','同人主链HTTP/数据库/审计一致'),('EXCEL_RECOVERY','Excel错行/重复/中断恢复'),
        ('BACKUP_RESTORE','独立恢复库逐项对账'),('WINDOWS','Windows125%/文件选择器/打印'),
        ('CLIENT_SIGNOFF','校方样本和交付验收确认'),('LICENSE_REVIEW','逐组件许可与交付资料核对')]:
        add(code,title,'NOT_VERIFIED','需独立验收证据；本命令不代签、不伪造通过')
    blocked=any(c['status']=='BLOCKED' for c in checks)
    return {'schema':'yueke.first-delivery.preflight.1','generated_at':datetime.now(timezone.utc).isoformat(),
        'tenant_id':tenant_id,'mode':'READ_ONLY','database_vendor':connection.vendor,
        'overall':'BLOCKED' if blocked else 'NEEDS_ACCEPTANCE','release_approved':False,
        'checks':checks,'note':'技术检查通过也不等于校方验收，未执行项不可用PASS替代。'}


class Command(BaseCommand):
    help='首单只读预检：输出技术阻断和待人工验收项；不迁移、不建人、不清库。'
    def add_arguments(self, parser):
        parser.add_argument('--tenant-id', type=int, required=True)
        parser.add_argument('--report', required=True, help='JSON报告路径；不包含数据库密码或个人记录')
    def handle(self,*args,**options):
        if options['tenant_id'] <= 0:
            raise CommandError('tenant-id必须为明确的正整数学校标识')
        report=collect_report(options['tenant_id'])
        dest=Path(options['report']).expanduser()
        dest.parent.mkdir(parents=True,exist_ok=True)
        # Atomic, owner-only output. Never leave a truncated previous report.
        fd, temp_name = tempfile.mkstemp(prefix='.hr-preflight-', dir=dest.parent)
        try:
            with os.fdopen(fd,'w',encoding='utf-8') as stream:
                json.dump(report,stream,ensure_ascii=False,indent=2)
                stream.write('\n')
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_name,dest)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
        self.stdout.write(str(dest))
        if report['overall']=='BLOCKED':
            raise CommandError('存在技术阻断，报告已保存；未执行任何修复写操作',returncode=2)
        raise CommandError('技术检查结束，但仍缺独立业务/客户验收；不可直接标记可交付',returncode=3)
