#!/usr/bin/env bash
# Explicit operator-only gate; creates/drops Django's ISOLATED test database.
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ "${HR_ISOLATED_MYSQL_ACCEPTANCE:-}" != "YES_I_CONFIRM_TEST_DATABASE" ]]; then
  echo '拒绝执行：请先配置独立 MySQL 验收实例，并设置 HR_ISOLATED_MYSQL_ACCEPTANCE=YES_I_CONFIRM_TEST_DATABASE。'
  echo '本脚本会创建/销毁 Django 测试库；禁止对正在服务的生产数据库使用。'
  exit 2
fi
python scripts/check_first_use_assets.py
python manage.py check
python manage.py shell -c 'from django.db import connection; from django.conf import settings; d=settings.DATABASES["default"]; n=(d.get("TEST") or {}).get("NAME") or ("test_"+str(d["NAME"])); assert connection.vendor == "mysql", "必须是真实MySQL"; assert str(n).startswith("test_") and n != d["NAME"], "必须明确使用 test_ 开头的隔离测试库"; print("目标测试库:",n)'
python manage.py makemigrations --check --dry-run
python manage.py test \
  base.test_minimal_first_use \
  base.test_round3_production_bootstrap \
  hr_staff.tests.test_minimal_import_mysql \
  hr_staff.tests.test_round4_export_import \
  hr_staff.tests.test_imports \
  --noinput
