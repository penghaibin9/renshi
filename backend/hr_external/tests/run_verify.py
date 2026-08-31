"""hr_external 轻量验证 runner（不加载 Horilla 全栈依赖）。

原理：在 django.setup() 前向 sys.modules 注入 horilla.urls 空壳，
使 hr_structure/hr_staff/hr_external 的 AppConfig.ready() 路由挂载 hook 无需导入完整 Horilla。

运行：
    python hr_external/tests/run_verify.py                 # check + migrate + test
    python hr_external/tests/run_verify.py check
    python hr_external/tests/run_verify.py test hr_external.tests.test_s1
"""

import os
import sys
import types

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_RENSHI_ROOT = os.path.dirname(os.path.dirname(_THIS_DIR))
if _RENSHI_ROOT not in sys.path:
    sys.path.insert(0, _RENSHI_ROOT)

# ---- 屏蔽真实 horilla.urls，避免拉入 notifications/pandas/PIL 等全栈依赖 ----
_shim = types.ModuleType("horilla")
sys.modules.setdefault("horilla", _shim)
_urls = types.ModuleType("horilla.urls")
_urls.urlpatterns = []
sys.modules["horilla.urls"] = _urls

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "hr_external.tests.mini_settings")

import django  # noqa: E402

django.setup()

# 限制加载的迁移，避免 hr_structure/hr_staff 内部的自动生成迁移冲突
from django.conf import settings as _settings_conf
_override = {
    "hr_external": None,  # None = 自动
}
_mm = getattr(_settings_conf, "MIGRATION_MODULES", None) or {}
_mm.update(_override)

from django.core import management  # noqa: E402

if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        args = ["check", "test"]
    i = 0
    while i < len(args):
        cmd = args[i]
        if cmd == "test":
            labels = args[i + 1 :] or ["hr_external"]
            management.call_command(cmd, *labels, verbosity=1)
            break
        management.call_command(cmd, verbosity=1)
        i += 1
    print("HR08_VERIFY_DONE")
