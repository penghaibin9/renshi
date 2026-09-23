"""Interactive school opening. No anonymous HTTP registration or default password."""
import getpass
import os
import sys
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from base.management.commands.bootstrap_production_admin import PASSWORD_ENV

class Command(BaseCommand):
    help = '首次开户：依次填写学校名称、管理员姓名、邮箱和密码；地址电话以后补。'

    def handle(self, *args, **options):
        if not getattr(settings, 'IS_PRODUCTION', False):
            raise CommandError('请先完成正式环境配置和迁移；此命令不绕过安全检查。')
        if not sys.stdin.isatty():
            raise CommandError('交互开户需要终端；自动化部署请调用 bootstrap_production_admin，并通过临时环境变量提供密码。')
        self.stdout.write('学校名称、管理员姓名、邮箱和密码为本次唯一必填项。现有学校不会被覆盖。')
        name = input('学校名称：').strip()
        admin = input('首位管理员姓名：').strip()
        email = input('管理员邮箱（同时作为登录账号）：').strip()
        password = getpass.getpass('管理员密码（不会显示）：')
        if password != getpass.getpass('再次输入密码：'):
            raise CommandError('两次密码不一致；尚未创建学校或账号。')
        old = os.environ.get(PASSWORD_ENV)
        try:
            os.environ[PASSWORD_ENV] = password
            call_command('bootstrap_production_admin', '--school-name', name, '--admin-name', admin,
                         '--email', email, stdout=self.stdout, stderr=self.stderr)
        finally:
            if old is None: os.environ.pop(PASSWORD_ENV, None)
            else: os.environ[PASSWORD_ENV] = old
