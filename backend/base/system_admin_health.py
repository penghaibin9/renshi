"""Read-only health/readiness helpers for the standalone-school admin center.

The standalone-school system-management cockpit must never become a second
source of truth.  This module only reads existing authorities and deployment
configuration, then turns them into actionable status items for a school IT
administrator.  It deliberately never returns passwords, tokens or secret
values.
"""
from __future__ import annotations

import json
from pathlib import Path

from django.conf import settings
from django.db import connection

from base.models import Company, Department, DynamicEmailConfiguration, JobPosition


def _setting_is_real(name: str, *, min_length: int = 1) -> bool:
    value = str(getattr(settings, name, "") or "").strip()
    if len(value) < min_length:
        return False
    lowered = value.lower()
    return not (
        lowered.startswith("change-me")
        or "example" in lowered
        or lowered in {"django-insecure-default-key", "localhost"}
    )


def installation_mode() -> str:
    value = str(getattr(settings, "HR_INSTALLATION_MODE", "standalone_school") or "").strip().lower()
    if value not in {"standalone_school", "saas_platform"}:
        return "standalone_school"
    return value


def _school_scope(selected_company):
    companies = Company.objects.order_by("id")
    count = companies.count()
    selected = None
    if selected_company and selected_company != "all":
        selected = companies.filter(id=selected_company).first()
    if selected is None and count == 1:
        selected = companies.first()
    return companies, count, selected


def _latest_backup_summary():
    root = Path(str(getattr(settings, "PRODUCTION_BACKUP_ROOT", "") or ""))
    summary = {
        "root_configured": bool(str(root)) and str(root) not in {".", ""},
        "root_exists": False,
        "latest_name": "",
        "latest_created_at": "",
        "latest_bytes": 0,
        "latest_valid_manifest": False,
    }
    try:
        if not root.exists() or not root.is_dir():
            return summary
        summary["root_exists"] = True
        bundles = sorted(
            (
                item
                for item in root.iterdir()
                if item.is_dir()
                and not item.is_symlink()
                and (item / "manifest.json").is_file()
            ),
            key=lambda item: item.name,
            reverse=True,
        )
        if not bundles:
            return summary
        latest = bundles[0]
        manifest = json.loads((latest / "manifest.json").read_text(encoding="utf-8"))
        artifacts = manifest.get("artifacts") or {}
        summary.update(
            {
                "latest_name": latest.name,
                "latest_created_at": str(manifest.get("created_at") or ""),
                "latest_bytes": sum(int((meta or {}).get("bytes") or 0) for meta in artifacts.values()),
                "latest_valid_manifest": manifest.get("format") == "renshi-production-backup-v1" and bool(artifacts),
            }
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        # The UI must stay available when the backup disk is absent/corrupt.
        # Validation/restoration remains the authority for declaring a bundle valid.
        return summary
    return summary


def _status(code: str, title: str, state: str, detail: str, action: str = ""):
    return {
        "code": code,
        "title": title,
        "state": state,
        "detail": detail,
        "action": action,
    }


def build_system_admin_health(*, selected_company, metrics):
    """Return a secret-free standalone-school runtime snapshot.

    ``metrics`` comes from the already company-scoped account query in the
    system-admin view.  Reusing it avoids broadening the school data scope.
    """
    companies, company_count, school = _school_scope(selected_company)
    mode = installation_mode()

    department_count = 0
    position_count = 0
    mail_configured = False
    if school is not None:
        department_count = Department.objects.filter(company_id=school).distinct().count()
        position_count = JobPosition.objects.filter(company_id=school).distinct().count()
        mail_configured = DynamicEmailConfiguration.objects.filter(
            company_id=school,
            host__isnull=False,
        ).exclude(host="").exists()

    backup = _latest_backup_summary()
    db_vendor = getattr(connection, "vendor", "") or "unknown"
    allowed_hosts = list(getattr(settings, "ALLOWED_HOSTS", []) or [])
    debug = bool(getattr(settings, "DEBUG", False))
    mfa = bool(getattr(settings, "TWO_FACTORS_AUTHENTICATION", False))
    backup_key_ready = _setting_is_real("PRODUCTION_BACKUP_ENCRYPTION_KEY", min_length=32)
    encryption_ready = _setting_is_real("FIELD_ENCRYPTION_KEYS", min_length=16)
    secret_key_ready = _setting_is_real("SECRET_KEY", min_length=32)
    platform_operations_enabled = bool(getattr(settings, "PLATFORM_OPERATIONS_ENABLED", False))

    checks = []
    if mode == "standalone_school":
        if company_count == 1:
            checks.append(_status("school", "学校主体", "ok", f"已绑定：{school.company}"))
        elif company_count == 0:
            checks.append(_status("school", "学校主体", "blocker", "尚未创建学校主体。", "先创建学校基本信息"))
        else:
            checks.append(_status("school", "学校主体", "blocker", f"检测到 {company_count} 个学校/单位记录；单校独立版应明确唯一学校主体。", "清理或确认部署模式"))
    else:
        checks.append(_status("mode", "部署模式", "info", "当前配置为平台模式，不属于本次单校独立版范围。"))

    if mode == "standalone_school":
        checks.append(
            _status(
                "platform_boundary",
                "平台接口边界",
                "ok" if not platform_operations_enabled else "warning",
                "单校版未暴露平台主管临时进入学校接口。" if not platform_operations_enabled else "单校版仍启用了平台操作接口。",
                "关闭 PLATFORM_OPERATIONS_ENABLED" if platform_operations_enabled else "",
            )
        )

    checks.append(
        _status(
            "org",
            "组织岗位",
            "ok" if department_count and position_count else "warning",
            f"部门 {department_count} 个，岗位 {position_count} 个。",
            "至少完成部门和岗位基线" if not (department_count and position_count) else "",
        )
    )
    checks.append(
        _status(
            "roles",
            "管理员与角色",
            "ok" if metrics.get("roles") and not metrics.get("accounts_without_role") else "warning",
            f"角色 {metrics.get('roles', 0)} 个；未分角色账号 {metrics.get('accounts_without_role', 0)} 个；直接授权账号 {metrics.get('direct_permission_accounts', 0)} 个。",
            "优先用角色授权，减少个人直接权限" if metrics.get("accounts_without_role") or metrics.get("direct_permission_accounts") else "",
        )
    )
    checks.append(
        _status(
            "database",
            "数据库",
            "ok" if db_vendor == "mysql" else "blocker",
            f"当前数据库：{db_vendor}。正式单校版要求 MySQL。",
            "切换到 MySQL" if db_vendor != "mysql" else "",
        )
    )
    checks.append(
        _status(
            "security",
            "生产安全基线",
            "ok" if (not debug and secret_key_ready and encryption_ready and "*" not in allowed_hosts) else "warning",
            "DEBUG、Secret Key、字段加密和 Allowed Hosts 已按生产基线核对。" if (not debug and secret_key_ready and encryption_ready and "*" not in allowed_hosts) else "仍有生产安全配置需要核对。",
            "按 .env.dist 完成生产安全参数" if (debug or not secret_key_ready or not encryption_ready or "*" in allowed_hosts) else "",
        )
    )
    checks.append(
        _status(
            "mfa",
            "管理员二次验证",
            "ok" if mfa else "warning",
            "已启用 MFA。" if mfa else "尚未启用 MFA；正式环境建议管理员启用二次验证。",
            "启用 TWO_FACTORS_AUTHENTICATION" if not mfa else "",
        )
    )
    checks.append(
        _status(
            "mail",
            "邮件通知",
            "ok" if mail_configured else "info",
            "学校邮件服务器已配置。" if mail_configured else "尚未配置学校邮件服务器；不影响基础人事办理，但会影响邮件通知/MFA。",
            "需要邮件能力时完成 SMTP 配置" if not mail_configured else "",
        )
    )
    backup_ok = backup_key_ready and backup.get("latest_valid_manifest")
    checks.append(
        _status(
            "backup",
            "备份恢复",
            "ok" if backup_ok else "warning",
            (
                f"最近备份：{backup.get('latest_created_at') or backup.get('latest_name')}。"
                if backup.get("latest_valid_manifest")
                else "尚未发现可识别的生产备份清单。"
            ),
            "配置备份密钥并完成一次隔离恢复演练" if not backup_ok else "",
        )
    )

    blockers = [item for item in checks if item["state"] == "blocker"]
    warnings = [item for item in checks if item["state"] == "warning"]
    return {
        "mode": mode,
        "mode_label": "单校独立部署版" if mode == "standalone_school" else "平台 SaaS 模式",
        "school": school,
        "company_count": company_count,
        "department_count": department_count,
        "position_count": position_count,
        "mail_configured": mail_configured,
        "database_vendor": db_vendor,
        "environment": str(getattr(settings, "HORILLA_ENV", "") or "未标记"),
        "timezone": str(getattr(settings, "TIME_ZONE", "") or ""),
        "mfa_enabled": mfa,
        "backup": backup,
        "checks": checks,
        "blocker_count": len(blockers),
        "warning_count": len(warnings),
        "ready_for_runtime_acceptance": not blockers,
    }
