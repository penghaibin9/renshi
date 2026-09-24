#!/usr/bin/env bash
set -euo pipefail
WORK=/tmp/mature-hr
mkdir -p "$WORK/evidence"
cd "$WORK"
SHARE_ID="_BvMl6AVaiJM"
FILE_ID="01a0d48b49d87634920e5d69692c811b"
API="https://api.firestorage.ai/dev/file"
curl -fsS -X POST "$API/shares/$SHARE_ID/files/$FILE_ID/download" -H "Content-Type: application/json" -d '{}' > download.json
URL="$(python -c 'import json; print(json.load(open("download.json"))["downloadUrl"])')"
curl -fL "$URL" -o mature_hr.zip
echo "2cadf361f85917194be789498b269a199f6779337d10c68f98abde39e2fb2027  mature_hr.zip" | sha256sum -c -
mkdir -p snapshot
unzip -q mature_hr.zip -d snapshot
ROOT="$(dirname "$(find snapshot -maxdepth 3 -name manage.py -print -quit)")"
test -n "$ROOT"
ROOT="$(cd "$ROOT" && pwd)"
sudo apt-get update
sudo apt-get install -y default-libmysqlclient-dev pkg-config
python -m pip install --upgrade pip
python -m pip install -r "$ROOT/requirements.lock"
python -m pip install pytest playwright==1.55.0
python -m playwright install --with-deps chromium
FERNET="$(python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
BOOTSTRAP_PASSWORD="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
{
  echo "SNAPSHOT_ROOT=$ROOT"
  echo "PYTHONPATH=$ROOT/backend:$ROOT"
  echo "FIELD_ENCRYPTION_KEYS=ci:$FERNET"
  echo "HR_BOOTSTRAP_ADMIN_PASSWORD=$BOOTSTRAP_PASSWORD"
  echo "HR_V1_BROWSER_PASSWORD=$BOOTSTRAP_PASSWORD"
} >> "$GITHUB_ENV"
python -m py_compile "$ROOT/backend/hr_staff/models/academic_profile.py" "$ROOT/backend/hr10_development/models/competency.py" "$ROOT/backend/hr_self/services/case_service.py"
node --check "$ROOT/frontend/static/hr/js/pages/hr10-insights.js"
node --check "$ROOT/frontend/static/hr/js/pages/hr17-cases.js"
