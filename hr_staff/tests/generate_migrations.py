"""生成 hr_staff 迁移的轻量 runner（不加载 Horilla 全栈依赖）。

原理：在 django.setup() 前向 sys.modules 注入 horilla.urls 空壳，
使 hr_structure/hr_staff 的 AppConfig.ready() 路由挂载 hook 无需导入完整 Horilla。
运行：
    C:\\Users\\10850\\.venvs\\hr03\\Scripts\\python.exe hr_staff/tests/generate_migrations.py
"""

import os
import sys
import types

# 确保 renshi 根目录在 sys.path（脚本按路径运行时 sys.path[0] 是脚本所在目录）
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_RENSHI_ROOT = os.path.dirname(os.path.dirname(_THIS_DIR))
if _RENSHI_ROOT not in sys.path:
    sys.path.insert(0, _RENSHI_ROOT)

# ---- 屏蔽真实 horilla.urls，避免拉入 notifications/pandas/PIL 等全栈依赖 ----
_shim = types.ModuleType("horilla")
_sys = sys.modules.setdefault("horilla", _shim)
_urls = types.ModuleType("horilla.urls")
_urls.urlpatterns = []
sys.modules["horilla.urls"] = _urls

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "hr_staff.tests.mini_settings")

import django  # noqa: E402

django.setup()

from django.core import management  # noqa: E402

if __name__ == "__main__":
    import sys as _sys

    commands = _sys.argv[1:] or ["makemigrations", "check", "migrate"]
    for cmd in commands:
        if cmd == "makemigrations":
            management.call_command("makemigrations", "hr_staff", verbosity=1)
        elif cmd == "migrate":
            management.call_command("migrate", verbosity=1)
        elif cmd == "test":
            management.call_command("test", "hr_staff", verbosity=2)
        else:
            management.call_command(cmd, verbosity=1)
    print("HR03_VERIFY_DONE")
