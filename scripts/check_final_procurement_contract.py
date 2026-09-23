#!/usr/bin/env python3
"""Static final procurement-closure gate (no Django import required)."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = {
    "views": ROOT / "backend/base/views.py",
    "urls": ROOT / "backend/base/urls.py",
    "forms": ROOT / "backend/base/forms.py",
    "refs": ROOT / "backend/base/permission_refs.py",
    "filters": ROOT / "backend/base/templatetags/basefilters.py",
    "theme_perm": ROOT / "backend/horilla_theme/templates/base/auth/permission_table.html",
    "group_lines": ROOT / "backend/base/templates/base/auth/group_lines.html",
    "init": ROOT / "backend/base/management/commands/export_school_initialization_snapshot.py",
    "acceptance": ROOT / "scripts/run_hr_acceptance_gate.py",
    "builder": ROOT / "scripts/build_procurement_acceptance_package.py",
    "perf": ROOT / "scripts/run_procurement_performance_probe.py",
    "checklist": ROOT / "docs/qa/FINAL_PROCUREMENT_ACCEPTANCE_CHECKLIST.md",
    "crosswalk": ROOT / "docs/qa/PROCUREMENT_14_ITEM_CROSSWALK.md",
    "sla": ROOT / "docs/SUPPORT_SLA_PROCUREMENT_BASELINE.md",
    "admin": ROOT / "docs/ADMIN_TRAINING_GUIDE.md",
    "operator": ROOT / "docs/OPERATOR_TRAINING_GUIDE.md",
    "manual": ROOT / "docs/USER_MANUAL_HR01_HR18.md",
    "trial": ROOT / "docs/qa/TRIAL_RUN_RECORD_TEMPLATE.json",
    "training": ROOT / "docs/qa/TRAINING_RECORD_TEMPLATE.csv",
    "remediation": ROOT / "docs/qa/REMEDIATION_REGISTER_TEMPLATE.csv",
    "external": ROOT / "docs/qa/EXTERNAL_INTEGRATION_ACCEPTANCE_TEMPLATE.json",
}
text = {k: p.read_text(encoding="utf-8-sig") if p.is_file() else "" for k, p in FILES.items()}
checks = []

def record(name, ok, note):
    checks.append({"name": name, "ok": bool(ok), "note": note})

def allin(key, *needles):
    return all(n in text[key] for n in needles)

# RBAC exactness + copy semantics
record("permission_remove_uses_url_ids", allin("views", "id=gid", "id=pid") and "Group.objects.get(id=1)" not in text["views"], "role permission removal must mutate the requested role/permission")
record("permission_remove_row_lock", "Group.objects.select_for_update()" in text["views"], "RBAC mutation serializes the role row")
record("permission_remove_post_only", '@require_http_methods(["POST"])' in text["views"], "RBAC destructive action is POST-only")
record("role_copy_route", "group-permission-copy/<int:gid>/" in text["urls"], "role copy has an explicit endpoint")
record("role_copy_only_permissions", allin("views", "copied.permissions.set(source.permissions.all())", "memberships_copied=false", "data_scopes_copied=false"), "copy must not duplicate membership/data scope")
record("role_copy_ui_warning", "Members and organization scope will not be copied" in text["group_lines"], "UI states the non-escalation boundary")
record("permission_refs_exact_helper", allin("refs", "content_type__app_label", "Permission reference", "ambiguous"), "bare codenames fail closed when ambiguous")
record("group_form_qualified_permissions", 'perm.content_type.app_label' in text["forms"] and "resolve_permission_refs" in text["forms"], "role form uses app-qualified permission refs")
record("direct_user_permission_exact", "resolve_permission_refs(all_refs)" in text["views"], "direct user permission mutation is exact")
record("template_app_qualified_values", "{{ perm.app_label }}.add_{{ model.model_name }}" in text["theme_perm"], "permission UI posts app-qualified refs")
record("selected_permissions_qualified", "permission_refs(perms)" in text["filters"] and "user.get_all_permissions()" in text["filters"], "pre-selection values match qualified UI contract")

# Initialization snapshot
record("init_command_exists", FILES["init"].is_file(), "school initialization snapshot command exists")
record("init_secret_policy", allin("init", '"containsPasswords": False', '"containsTokens": False', '"containsEncryptionKeys": False'), "snapshot explicitly excludes runtime secrets")
record("init_roles", allin("init", '"roles": roles', '"permissions": sorted'), "roles and exact permissions are captured")
record("init_admins", '"administrators": admins' in text["init"], "administrator account inventory is captured without passwords")
record("init_dictionary", '"dictionaries": dictionaries' in text["init"], "initial configuration/dictionary rows are captured")
record("init_interface_mapping", '"interfaceMappings": mappings' in text["init"], "HR18 interface mappings are captured")
record("init_migrations", '"migrations": migration_rows' in text["init"], "applied migration state is captured")
record("init_sha_sidecar", ".sha256" in text["init"] and "hashlib.sha256" in text["init"], "snapshot has detached SHA-256")

# Runtime acceptance and performance
record("acceptance_runs_init", '"school-initialization-snapshot"' in text["acceptance"] and "export_school_initialization_snapshot" in text["acceptance"], "production-shaped acceptance actually generates initialization evidence")
record("acceptance_final_pack_args", allin("acceptance", "--procurement-pack-output", "--procurement-performance-json", "--trial-run-record", "--remediation-register", "--training-record", "--external-integration-record"), "final package inputs are first-class acceptance arguments")
record("acceptance_requires_all_final_inputs", "if not all(procurement_args)" in text["acceptance"], "partial final evidence cannot be silently ignored")
record("performance_default_100", "default=100" in text["perf"] and "--concurrency" in text["perf"], "performance probe defaults to 100 concurrent users")
record("performance_3s_5s", "default=3000.0" in text["perf"] and "default=5000.0" in text["perf"], "procurement performance thresholds are executable")
record("performance_get_only", 'method="GET"' in text["perf"], "load probe is read-only")
record("performance_manual_guard", "--allow-load" in text["perf"] and "REFUSED" in text["perf"], "load generation requires explicit authorization")

# Strict final evidence builder
record("builder_exists", FILES["builder"].is_file(), "final evidence builder exists")
record("builder_runtime_strict", allin("builder", 'data.get("status") != "PASSED"', '"school-initialization-snapshot"', '"ready-endpoint"'), "runtime evidence must be fully passed")
record("builder_performance_strict", allin("builder", "concurrency is below 100", "3000 ms", "5000 ms", '"NORMAL"', '"ANALYTICS"'), "100-concurrency/3s/5s evidence is enforced")
record("builder_trial_dual_confirmation", allin("builder", 'data.get("buyerConfirmed") is not True', 'data.get("supplierConfirmed") is not True', "sampled business flows"), "trial run cannot be an unsigned empty template")
record("builder_training_roles", allin("builder", '{"ADMIN", "OPERATOR"}.issubset(roles)', "COMPLETED", "CONFIRMED"), "administrator and operator training are both required")
record("builder_remediation_closed", allin("builder", '!= "CLOSED"', '!= "PASS"', '!= "ACCEPTED"'), "every remediation row must be closed/verified/accepted")
record("builder_external_real_or_na", allin("builder", '{"REQUIRED", "NOT_APPLICABLE"}', "required integration", "needs rationale"), "external interfaces must pass or be explicitly not applicable")
record("builder_incomplete_no_certificate", '"releaseCertificate": bool(complete)' in text["builder"] and "if complete:" in text["builder"], "incomplete evidence cannot get a release certificate")
record("builder_manifest_sha", allin("builder", '"manifest.json"', '"sha256"', '.sha256'), "final evidence package is hash-manifested")
record("builder_allow_incomplete_explicit", "--allow-incomplete" in text["builder"], "incomplete diagnostic packs require an explicit option")

# Delivery documents / source-derived procurement requirements
record("trial_template", FILES["trial"].is_file() and '"sampledFlows"' in text["trial"], "trial-run template exists")
record("training_template", FILES["training"].is_file() and "ADMIN" in text["training"] and "OPERATOR" in text["training"], "two-role training template exists")
record("remediation_template", FILES["remediation"].is_file() and "school_acceptance" in text["remediation"], "remediation register includes school acceptance")
record("external_template", FILES["external"].is_file() and "SCHOOL_SSO" in text["external"] and "SCHOOL_DATA_HUB" in text["external"], "external integration template covers school SSO/data hub")
record("final_checklist", FILES["checklist"].is_file() and "最终采购级验收清单" in text["checklist"], "single final checklist exists")
record("crosswalk_14_items", FILES["crosswalk"].is_file() and all(f"| {i} " in text["crosswalk"] for i in range(1, 15)), "all 14 procurement items are classified")
record("non_hr_points_not_faked", "不直接适用" in text["crosswalk"] and "教师积分激励" in text["crosswalk"], "non-HR-specific incentive business is not fabricated")
record("user_manual_18_domains", FILES["manual"].is_file() and all(f"| HR{i:02d} |" in text["manual"] for i in range(1, 19)), "user manual covers HR01-HR18")
record("admin_training_guide", FILES["admin"].is_file() and "复制已有角色权限" in text["admin"], "administrator training covers RBAC and operations")
record("operator_training_guide", FILES["operator"].is_file() and "Excel 预览" in text["operator"] and "HR12" in text["operator"], "operator training covers core workflows")
record("sla_one_year", "不少于 1 年" in text["sla"], "warranty baseline matches procurement reference")
record("sla_severe_response", "30 分钟内响应" in text["sla"] and "2 小时内提供处置方案" in text["sla"], "severe-incident response baseline is frozen")
record("sla_general_response", "一般功能故障：2 小时内响应" in text["sla"], "general incident response baseline is frozen")
record("sla_consulting", "1 个工作日内响应" in text["sla"], "configuration/consulting response baseline is frozen")
record("sla_annual_fee", "不高于合同金额的 10%" in text["sla"], "post-warranty procurement baseline is documented")
record("handover_in_final_checklist", "开放学校移交包" in text["checklist"] and "逐表行数一致" in text["checklist"], "supplier-exit portability remains a release gate")
record("no_static_release_claim", "只有结果 `COMPLETE`" in text["checklist"], "documents do not claim source checks equal runtime acceptance")

passed = sum(1 for item in checks if item["ok"])
result = {
    "gate": "FINAL_PROCUREMENT_SOURCE_CLOSURE_STATIC",
    "status": "PASS" if passed == len(checks) else "FAIL",
    "passed": passed,
    "total": len(checks),
    "checks": checks,
    "scopeNote": "Source-level procurement closure only. Real MySQL/Django, representative performance, school trial run, training and external integrations remain runtime/external evidence.",
}
print(json.dumps(result, ensure_ascii=False, indent=2))
raise SystemExit(0 if result["status"] == "PASS" else 1)
