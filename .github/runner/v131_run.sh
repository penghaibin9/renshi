#!/usr/bin/env bash
set -euo pipefail

cd "$SNAPSHOT_ROOT"
export HR_V1_BROWSER_ARTIFACT_DIR=/tmp/v131/evidence
mkdir -p "$HR_V1_BROWSER_ARTIFACT_DIR"

wait_url() {
  local url="$1"
  for i in $(seq 1 60); do
    if curl -fsS "$url" >/dev/null 2>&1; then return 0; fi
    sleep 1
  done
  echo "Timed out waiting for $url" >&2
  return 1
}

python manage.py migrate --noinput

python - <<'PY'
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

python manage.py bootstrap_production_admin   --username ci-admin   --email ci-admin@example.test   --first-name CI   --last-name Admin   --school-name "CI University"   --allow-non-production

python manage.py bootstrap_hr_configuration_v1 --tenant 1
python manage.py bootstrap_hr_configuration_v1 --tenant 1

python manage.py test   hr_integration.tests.test_sso_runtime   hr_integration.tests.test_sso_protocol_harness   hr_integration.tests.test_sso_ldap_logic_harness   --verbosity 2 | tee "$HR_V1_BROWSER_ARTIFACT_DIR/sso-unit-harness.log"

nohup python scripts/hr_config_integration_mock_school.py   > "$HR_V1_BROWSER_ARTIFACT_DIR/mock-school.log" 2>&1 &
nohup python manage.py runserver 127.0.0.1:8000 --noreload   > "$HR_V1_BROWSER_ARTIFACT_DIR/django.log" 2>&1 &

wait_url http://127.0.0.1:9011/health
wait_url http://127.0.0.1:8000/login/

python scripts/hr_config_integration_browser.py
python scripts/verify_hr_config_integration_v1.py   | tee "$HR_V1_BROWSER_ARTIFACT_DIR/config-integration-db-gate.log"

python manage.py shell < "$GITHUB_WORKSPACE/.github/runner/v131_seed_sso.py"   | tee "$HR_V1_BROWSER_ARTIFACT_DIR/sso-seed.log"

nohup python scripts/hr_sso_mock_oidc.py   > "$HR_V1_BROWSER_ARTIFACT_DIR/mock-oidc.log" 2>&1 &
wait_url http://localhost:9012/health

python scripts/hr_sso_runtime_browser.py

python manage.py hr_config_integration_v1_gate   --tenant 1   --require-published HR05   --require-verified MASTER_DATA   --require-mapping   --require-sso-runtime   --json-output "$HR_V1_BROWSER_ARTIFACT_DIR/implementation-gate.json"   | tee "$HR_V1_BROWSER_ARTIFACT_DIR/implementation-gate.log"

echo "V1.3.1 FIRST-SCHOOL SSO RUNNER GATE: PASS"
