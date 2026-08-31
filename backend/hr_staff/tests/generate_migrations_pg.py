"""在 PostgreSQL（Docker db）上验证 HR03：clean-DB 迁移 + check + 全量测试。

用法：
    $env:DJANGO_SETTINGS_MODULE="hr_staff.tests.mini_settings_pg"
    python hr_staff/tests/generate_migrations_pg.py [migrate|check|test]
"""

import os
import sys
import types

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_RENSHI_ROOT = os.path.dirname(os.path.dirname(_THIS_DIR))
if _RENSHI_ROOT not in sys.path:
    sys.path.insert(0, _RENSHI_ROOT)

_shim = types.ModuleType("horilla")
sys.modules.setdefault("horilla", _shim)
_urls = types.ModuleType("horilla.urls")
_urls.urlpatterns = []
sys.modules["horilla.urls"] = _urls

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "hr_staff.tests.mini_settings_pg")
os.environ.setdefault("PG_HOST", "127.0.0.1")
os.environ.setdefault("PG_PORT", "15432")

import django  # noqa: E402

django.setup()

from django.core import management  # noqa: E402

if __name__ == "__main__":
    commands = sys.argv[1:] or ["migrate", "check", "test"]
    for cmd in commands:
        if cmd == "migrate":
            management.call_command("migrate", verbosity=1)
        elif cmd == "test":
            management.call_command("test", "hr_staff", verbosity=2, interactive=False)
        else:
            management.call_command(cmd, verbosity=1)
    print("HR03_PG_VERIFY_DONE")
