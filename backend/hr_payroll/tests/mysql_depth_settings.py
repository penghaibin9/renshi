"""Opt-in isolated MySQL service tests. Never use these settings to serve the app.
This suite creates/destroys only a specifically named test database. It validates
current ORM/services; replay full project migrations separately on a clean clone.
"""
from .sqlite_settings import *  # noqa: F401,F403
import os,re
from django.core.exceptions import ImproperlyConfigured
if os.environ.get('HR15_ALLOW_ISOLATED_MYSQL_TEST')!='YES':
    raise ImproperlyConfigured('Set HR15_ALLOW_ISOLATED_MYSQL_TEST=YES only for an isolated test server')
name=os.environ.get('HR15_TEST_MYSQL_DATABASE','')
if not re.fullmatch(r'yueke_hr15_test_[a-z0-9_]{1,32}',name):
    raise ImproperlyConfigured('Test database must be named yueke_hr15_test_<suffix>; never select customer/platform databases')
DATABASES={'default':{'ENGINE':'django.db.backends.mysql','NAME':name,
    'HOST':os.environ.get('HR15_TEST_MYSQL_HOST','127.0.0.1'),
    'PORT':os.environ.get('HR15_TEST_MYSQL_PORT','3306'),
    'USER':os.environ.get('HR15_TEST_MYSQL_USER',''),
    'PASSWORD':os.environ.get('HR15_TEST_MYSQL_PASSWORD',''),
    'OPTIONS':{'charset':'utf8mb4','isolation_level':'read committed'},
    'TEST':{'NAME':name+'_run','CHARSET':'utf8mb4','COLLATION':'utf8mb4_unicode_ci'}}}
if not DATABASES['default']['USER']:raise ImproperlyConfigured('Dedicated test MySQL user required')
