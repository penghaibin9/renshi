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

# Restore the exact user-owned external assets referenced by the V1.3.1
# delivery manifest. The pack was extracted from the 2026-09-17 baseline and
# verified 25/25 against FIRST_USE_EXTERNAL_ASSETS.json before upload.
ASSET_SHARE_ID="qtTOLLp9XBvX"
ASSET_FILE_ID="01a0d2fd5104757bb4d0d84f10cc48ee"
curl -fsS -X POST "$API/shares/$ASSET_SHARE_ID/files/$ASSET_FILE_ID/download" \
  -H "Content-Type: application/json" -d '{}' > asset-download.json
ASSET_URL="$(python -c 'import json; print(json.load(open("asset-download.json"))["downloadUrl"])')"
curl -fL "$ASSET_URL" -o v131_external_assets.zip
echo "d5fd982dcbaf6693fb7ddbdd61f2c94547026af88c717102eca877cb371495d0  v131_external_assets.zip" | sha256sum -c -
unzip -oq v131_external_assets.zip -d "$ROOT"

ROOT_FOR_ASSET_CHECK="$ROOT" python - <<'PY'
from pathlib import Path
import hashlib, json, os
root=Path(os.environ["ROOT_FOR_ASSET_CHECK"])
manifest=json.loads((root/"FIRST_USE_EXTERNAL_ASSETS.json").read_text(encoding="utf-8"))
for item in manifest["files"]:
    p=root/item["path"]
    assert p.exists(), f"missing external asset: {item['path']}"
    digest=hashlib.sha256(p.read_bytes()).hexdigest()
    assert digest == item["sha256"], (item["path"], digest, item["sha256"])
print(f"external assets verified: {len(manifest['files'])}/{len(manifest['files'])}")
PY

# Build the generated Tailwind asset that is referenced by the clean V16 shell
# but intentionally not stored in the source snapshot.
cd "$ROOT"
npm ci
npm run build:css
test -s backend/horilla_theme/static/horilla_theme/assets/css/tailwind.css
cd "$WORK"

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
