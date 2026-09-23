#!/usr/bin/env bash
set -euo pipefail

WORK=/tmp/v131
mkdir -p "$WORK/evidence"
cd "$WORK"

SHARE_ID="tiaXiOC6z77s"
FILE_ID="01a0cdd960c3720bae09d25b06cf572e"
API="https://api.firestorage.ai/dev/file"
curl -fsS -X POST "$API/shares/$SHARE_ID/files/$FILE_ID/download"   -H "Content-Type: application/json" -d '{}' > download.json
URL="$(python -c 'import json; print(json.load(open("download.json"))["downloadUrl"])')"
curl -fL "$URL" -o v131.zip
echo "6a3a6632806815db393bfe29d19ca5d637ba99c62b30bbbe03a7ea1996759a15  v131.zip" | sha256sum -c -

rm -rf snapshot
mkdir snapshot
unzip -q v131.zip -d snapshot
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
{
  echo "SNAPSHOT_ROOT=$ROOT"
  echo "PYTHONPATH=$ROOT/backend:$ROOT"
  echo "FIELD_ENCRYPTION_KEYS=ci:$FERNET"
  echo "HR_BOOTSTRAP_ADMIN_PASSWORD=CI-Runtime-Only-4f7c-9Kp2"
  echo "HR_V1_BROWSER_PASSWORD=CI-Runtime-Only-4f7c-9Kp2"
} >> "$GITHUB_ENV"
