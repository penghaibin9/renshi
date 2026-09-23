"""Pure migration conflict rules; never merge accounts on username alone."""
from __future__ import annotations

SECURITY_FIELDS = ("password", "is_active", "is_staff", "is_superuser")

class LegacyIdentityConflict(ValueError):
    pass


def migration_action(source, target_by_id, target_by_username):
    if target_by_id is None and target_by_username is None:
        return "CREATE"
    if (target_by_id is None or target_by_username is None
            or target_by_id["id"] != target_by_username["id"]
            or target_by_id["id"] != source["id"]
            or target_by_id["username"] != source["username"]):
        raise LegacyIdentityConflict("旧账号与现有账号的编号或登录名冲突；不合并、不覆盖，请先核对身份")
    if any(target_by_id.get(key) != source.get(key) for key in SECURITY_FIELDS):
        raise LegacyIdentityConflict("同编号账号的安全状态或密码已不同；保留现有账号，不恢复旧密码或旧权限")
    return "EXACT_EXISTING"
