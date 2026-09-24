#!/usr/bin/env bash
set -euo pipefail
cd "$SNAPSHOT_ROOT"
EVIDENCE=/tmp/mature-hr/evidence
mkdir -p "$EVIDENCE"

python manage.py migrate --noinput | tee "$EVIDENCE/mysql-migrate.log"

python - <<'PY' | tee "$EVIDENCE/mysql-version.log"
import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "horilla.settings")
import django
django.setup()
from django.db import connection
with connection.cursor() as cursor:
    cursor.execute("SELECT VERSION()")
    version = str(cursor.fetchone()[0])
print("MYSQL_VERSION=" + version)
assert connection.vendor == "mysql"
assert version.startswith("8.4."), version
PY

python manage.py makemigrations hr_staff hr10_development hr_self --check --dry-run   | tee "$EVIDENCE/migration-drift.log"

DJANGO_SETTINGS_MODULE=hr_staff.tests.sqlite_settings   python -m django test hr_staff.tests.test_academic_profile hr_staff.tests.test_profile hr_staff.tests.test_pages -v 1   | tee "$EVIDENCE/hr03-regression.log"

DJANGO_SETTINGS_MODULE=hr10_development.tests.sqlite_settings   python -m django test hr10_development.tests.test_competency_matrix hr10_development.tests.test_hr10_workspace_v2 hr10_development.tests.test_public_identity_contract -v 1   | tee "$EVIDENCE/hr10-regression.log"

DJANGO_SETTINGS_MODULE=hr_self.tests.sqlite_settings   python -m django test hr_self.tests.test_service_cases hr_self.tests.test_ui_contract hr_self.tests.test_models hr_self.tests.test_catalog_search hr_self.tests.test_access_contract -v 1   | tee "$EVIDENCE/hr17-regression.log"

python manage.py shell < "$GITHUB_WORKSPACE/.github/runner/mature_hr_mysql_smoke.py"   | tee "$EVIDENCE/mature-hr-mysql-smoke.log"

python scripts/audit_hr_frontend_boundary.py | tee "$EVIDENCE/repoclean-boundary.json"

echo "MATURE_HR_INTEGRATION_GATE: PASS"
