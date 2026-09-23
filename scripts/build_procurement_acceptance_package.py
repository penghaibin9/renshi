#!/usr/bin/env python3
"""Build the final procurement acceptance evidence package.

The builder is intentionally strict: source code can create templates and test
harnesses, but it cannot manufacture school-side evidence.  A release
certificate is emitted only when runtime, performance, training, trial-run,
remediation and external-integration evidence is complete and machine-checkable.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHA_RE = re.compile(r"^[0-9a-f]{64}$")


class EvidenceError(RuntimeError):
    pass


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise EvidenceError(f"invalid JSON evidence: {path.name}") from exc
    if not isinstance(data, dict):
        raise EvidenceError(f"JSON evidence must be an object: {path.name}")
    return data


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _require_file(path: str | None, label: str) -> Path:
    if not path:
        raise EvidenceError(f"missing {label} evidence path")
    p = Path(path).expanduser().resolve()
    if not p.is_file():
        raise EvidenceError(f"missing {label} evidence file: {p}")
    return p


def validate_runtime(path: Path) -> dict:
    data = _read_json(path)
    if data.get("status") != "PASSED":
        raise EvidenceError("runtime acceptance status is not PASSED")
    if data.get("productionTouched") is not False or data.get("gitHubTouched") is not False:
        raise EvidenceError("runtime evidence does not prove isolated acceptance")
    phases = {item.get("name"): item.get("status") for item in data.get("phases", []) if isinstance(item, dict)}
    required = {
        "release",
        "django-check-deploy",
        "migration-drift",
        "migration-applied",
        "field-security-check",
        "hr01-hr18-tests",
        "bootstrap-first-admin",
        "school-initialization-snapshot",
        "backup-create",
        "backup-verify",
        "backup-restore",
        "restored-migration-check",
        "handover-create",
        "handover-verify",
        "handover-restore",
        "handover-restored-migration-check",
        "ready-endpoint",
    }
    missing = sorted(name for name in required if phases.get(name) != "PASSED")
    if missing:
        raise EvidenceError("runtime evidence missing PASSED phases: " + ", ".join(missing))
    snapshot_sha = str(data.get("initializationSnapshotSha256") or "").strip().lower()
    if snapshot_sha and not SHA_RE.fullmatch(snapshot_sha):
        raise EvidenceError("runtime initialization snapshot SHA-256 is invalid")
    return {
        "status": "PASS",
        "requiredPhases": sorted(required),
        "initializationSnapshotSha256": snapshot_sha or None,
        "source": path.name,
    }


def validate_initialization(path: Path) -> dict:
    data = _read_json(path)
    if data.get("kind") != "YUEKE_UNIVERSITY_HR_SCHOOL_INITIALIZATION_SNAPSHOT":
        raise EvidenceError("unexpected initialization snapshot kind")
    secret_policy = data.get("secretPolicy") or {}
    if any(secret_policy.get(k) is not False for k in ("containsPasswords", "containsTokens", "containsEncryptionKeys")):
        raise EvidenceError("initialization snapshot does not prove secret exclusion")
    if not isinstance(data.get("roles"), list) or not isinstance(data.get("migrations"), list):
        raise EvidenceError("initialization snapshot is structurally incomplete")
    return {"status": "PASS", "roles": len(data.get("roles", [])), "source": path.name}


def validate_performance(path: Path) -> dict:
    data = _read_json(path)
    if data.get("status") != "PASS":
        raise EvidenceError("performance evidence status is not PASS")
    if int(data.get("concurrency") or 0) < 100:
        raise EvidenceError("performance evidence concurrency is below 100")
    thresholds = data.get("thresholds") or {}
    if float(thresholds.get("normalMs") or 1e9) > 3000:
        raise EvidenceError("normal-page threshold exceeds 3000 ms")
    if float(thresholds.get("analyticsMs") or 1e9) > 5000:
        raise EvidenceError("analytics-page threshold exceeds 5000 ms")
    targets = data.get("targets") or []
    categories = {item.get("category") for item in targets if isinstance(item, dict) and item.get("pass") is True}
    if "NORMAL" not in categories or "ANALYTICS" not in categories:
        raise EvidenceError("performance evidence must include passing NORMAL and ANALYTICS targets")
    if any(item.get("pass") is not True for item in targets if isinstance(item, dict)):
        raise EvidenceError("one or more performance targets failed")
    return {"status": "PASS", "concurrency": data["concurrency"], "targets": len(targets), "source": path.name}


def validate_trial_run(path: Path) -> dict:
    data = _read_json(path)
    if data.get("status") != "PASS":
        raise EvidenceError("trial-run status is not PASS")
    if data.get("buyerConfirmed") is not True or data.get("supplierConfirmed") is not True:
        raise EvidenceError("trial-run requires buyer and supplier confirmation")
    flows = data.get("sampledFlows") or []
    if not flows or any(item.get("status") != "PASS" for item in flows if isinstance(item, dict)):
        raise EvidenceError("trial-run must contain passing sampled business flows")
    if not str(data.get("startAt") or "").strip() or not str(data.get("endAt") or "").strip():
        raise EvidenceError("trial-run start/end timestamps are required")
    if not str(data.get("buyerRepresentative") or "").strip() or not str(data.get("supplierRepresentative") or "").strip():
        raise EvidenceError("trial-run buyer/supplier representative names are required")
    return {"status": "PASS", "sampledFlows": len(flows), "source": path.name}


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = [dict(row) for row in reader]
    if not reader.fieldnames:
        raise EvidenceError(f"CSV has no header: {path.name}")
    return rows


def validate_training(path: Path) -> dict:
    rows = _read_csv(path)
    if not rows:
        raise EvidenceError("training record is empty")
    roles = set()
    for row in rows:
        if str(row.get("attendance_status") or "").strip().upper() != "COMPLETED":
            raise EvidenceError("all training rows must be COMPLETED")
        if str(row.get("acknowledgement") or "").strip().upper() != "CONFIRMED":
            raise EvidenceError("all training rows require CONFIRMED acknowledgement")
        if not str(row.get("participant") or "").strip() or not str(row.get("session_at") or "").strip():
            raise EvidenceError("training participant/session_at are required")
        roles.add(str(row.get("role") or "").strip().upper())
    if not {"ADMIN", "OPERATOR"}.issubset(roles):
        raise EvidenceError("training must include both ADMIN and OPERATOR participants")
    return {"status": "PASS", "records": len(rows), "roles": sorted(roles), "source": path.name}


def validate_remediation(path: Path) -> dict:
    rows = _read_csv(path)
    if not rows:
        raise EvidenceError("remediation register is empty; use an explicit NO_ISSUES row when applicable")
    for row in rows:
        issue_id = str(row.get("issue_id") or "").strip()
        if not issue_id:
            raise EvidenceError("remediation issue_id is required")
        if str(row.get("status") or "").strip().upper() != "CLOSED":
            raise EvidenceError(f"remediation {issue_id} is not CLOSED")
        if str(row.get("verification_status") or "").strip().upper() != "PASS":
            raise EvidenceError(f"remediation {issue_id} verification is not PASS")
        if str(row.get("school_acceptance") or "").strip().upper() != "ACCEPTED":
            raise EvidenceError(f"remediation {issue_id} lacks school acceptance")
    return {"status": "PASS", "records": len(rows), "source": path.name}


def validate_external(path: Path) -> dict:
    data = _read_json(path)
    rows = data.get("integrations")
    if not isinstance(rows, list):
        raise EvidenceError("external integration evidence must contain integrations[]")
    if not rows:
        if data.get("noExternalIntegrationsConfirmedByBuyer") is not True or data.get("noExternalIntegrationsConfirmedBySupplier") is not True:
            raise EvidenceError("empty external-integration set requires buyer+supplier confirmation")
    for row in rows:
        code = str(row.get("integrationCode") or "").strip()
        applicability = str(row.get("applicability") or "").strip().upper()
        status = str(row.get("status") or "").strip().upper()
        if not code or applicability not in {"REQUIRED", "NOT_APPLICABLE"}:
            raise EvidenceError("external integration code/applicability is invalid")
        if applicability == "REQUIRED" and status != "PASS":
            raise EvidenceError(f"required integration {code} is not PASS")
        if applicability == "NOT_APPLICABLE" and not str(row.get("rationale") or "").strip():
            raise EvidenceError(f"not-applicable integration {code} needs rationale")
        if row.get("buyerConfirmed") is not True or row.get("supplierConfirmed") is not True:
            raise EvidenceError(f"integration {code} lacks buyer/supplier confirmation")
    return {"status": "PASS", "records": len(rows), "source": path.name}


def _copy(stage: Path, source: Path, target_name: str) -> dict:
    target = stage / target_name
    shutil.copy2(source, target)
    return {"path": target_name, "bytes": target.stat().st_size, "sha256": _sha256(target)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-evidence")
    parser.add_argument("--initialization-snapshot")
    parser.add_argument("--performance-evidence")
    parser.add_argument("--trial-run-record")
    parser.add_argument("--remediation-register")
    parser.add_argument("--training-record")
    parser.add_argument("--external-integration-record")
    parser.add_argument("--output", required=True)
    parser.add_argument("--allow-incomplete", action="store_true")
    args = parser.parse_args(argv)

    validators = [
        ("runtime", args.runtime_evidence, validate_runtime, "runtime-evidence.json"),
        ("initialization", args.initialization_snapshot, validate_initialization, "school-initialization-snapshot.json"),
        ("performance", args.performance_evidence, validate_performance, "performance-evidence.json"),
        ("trialRun", args.trial_run_record, validate_trial_run, "trial-run.json"),
        ("remediation", args.remediation_register, validate_remediation, "remediation.csv"),
        ("training", args.training_record, validate_training, "training.csv"),
        ("externalIntegrations", args.external_integration_record, validate_external, "external-integrations.json"),
    ]

    results = {}
    failures = []
    resolved = {}
    for key, raw_path, validator, target_name in validators:
        try:
            p = _require_file(raw_path, key)
            resolved[key] = (p, target_name)
            results[key] = validator(p)
        except EvidenceError as exc:
            results[key] = {"status": "FAIL", "error": str(exc)}
            failures.append(f"{key}: {exc}")

    if (
        results.get("runtime", {}).get("status") == "PASS"
        and results.get("initialization", {}).get("status") == "PASS"
    ):
        declared = results["runtime"].get("initializationSnapshotSha256")
        actual = _sha256(resolved["initialization"][0])
        if declared and declared != actual:
            message = "initialization snapshot SHA-256 does not match runtime evidence"
            results["initialization"] = {"status": "FAIL", "error": message}
            failures.append(f"initialization: {message}")

    complete = not failures
    output = Path(args.output).expanduser().resolve()
    if output.suffix.lower() != ".zip":
        print("REFUSED: --output must end with .zip")
        return 2
    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="yueke-hr-acceptance-") as tmp:
        stage = Path(tmp)
        artifacts = []
        for key, (source, target_name) in resolved.items():
            artifacts.append(_copy(stage, source, target_name))
        for source, target_name in [
            (ROOT / "docs/qa/FINAL_PROCUREMENT_ACCEPTANCE_CHECKLIST.md", "FINAL_PROCUREMENT_ACCEPTANCE_CHECKLIST.md"),
            (ROOT / "docs/qa/PROCUREMENT_14_ITEM_CROSSWALK.md", "PROCUREMENT_14_ITEM_CROSSWALK.md"),
            (ROOT / "docs/SUPPORT_SLA_PROCUREMENT_BASELINE.md", "SUPPORT_SLA_PROCUREMENT_BASELINE.md"),
        ]:
            if source.is_file():
                artifacts.append(_copy(stage, source, target_name))

        summary = {
            "schemaVersion": 1,
            "kind": "YUEKE_UNIVERSITY_HR_FINAL_PROCUREMENT_ACCEPTANCE",
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "status": "COMPLETE" if complete else "INCOMPLETE",
            "releaseCertificate": bool(complete),
            "checks": results,
            "failures": failures,
            "interpretation": (
                "COMPLETE means all supplied runtime, performance, trial-run, remediation, training and external-integration evidence passed strict machine checks. "
                "It does not replace the buyer's formal signature/contract process."
            ),
        }
        summary_path = stage / "acceptance_summary.json"
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        artifacts.append({"path": summary_path.name, "bytes": summary_path.stat().st_size, "sha256": _sha256(summary_path)})

        if complete:
            cert = {
                "schemaVersion": 1,
                "releaseCertificate": True,
                "issuedAt": datetime.now(timezone.utc).isoformat(),
                "basis": "All final procurement acceptance evidence gates passed.",
            }
            cert_path = stage / "release_certificate.json"
            cert_path.write_text(json.dumps(cert, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            artifacts.append({"path": cert_path.name, "bytes": cert_path.stat().st_size, "sha256": _sha256(cert_path)})

        manifest = {"schemaVersion": 1, "status": summary["status"], "artifacts": sorted(artifacts, key=lambda x: x["path"])}
        manifest_path = stage / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        tmp_zip = output.with_suffix(output.suffix + ".tmp")
        tmp_zip.unlink(missing_ok=True)
        with zipfile.ZipFile(tmp_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
            for p in sorted(stage.iterdir(), key=lambda x: x.name):
                zf.write(p, arcname=p.name)
        os.replace(tmp_zip, output)

    digest = _sha256(output)
    output.with_suffix(output.suffix + ".sha256").write_text(f"{digest}  {output.name}\n", encoding="ascii")
    print(json.dumps({"status": "COMPLETE" if complete else "INCOMPLETE", "releaseCertificate": complete, "output": str(output), "sha256": digest, "failures": failures}, ensure_ascii=False, indent=2))
    if complete or args.allow_incomplete:
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
