"""Pure first-use rules. No database, browser storage or invented school facts."""
from __future__ import annotations
from collections.abc import Mapping

class BootstrapInputError(ValueError):
    pass

OPTIONAL_PROFILE_FIELDS = {
    "phone": (25, "管理员电话"),
    "company_address": (255, "学校地址"),
    "company_country": (50, "国家"),
    "company_state": (50, "省份"),
    "company_city": (50, "城市"),
    "company_zip": (20, "邮编"),
}

def normalize_bootstrap_options(options: Mapping) -> dict[str, str]:
    values = {}
    fields = {
        "company_name": (50, "学校名称"),
        "first_name": (150, "管理员姓名"),
        "email": (254, "管理员邮箱"),
        "last_name": (150, "管理员姓氏"),
        "username": (150, "登录账号"),
        **OPTIONAL_PROFILE_FIELDS,
    }
    for key, (limit, label) in fields.items():
        raw = options.get(key)
        value = "" if raw is None else str(raw).strip()
        if len(value) > limit:
            raise BootstrapInputError(f"{label}不能超过 {limit} 个字符")
        if any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise BootstrapInputError(f"{label}不能包含控制字符")
        values[key] = value
    for key, label in (("company_name", "学校名称"), ("first_name", "管理员姓名"), ("email", "管理员邮箱")):
        if not values[key]:
            raise BootstrapInputError(f"{label}不能为空")
    if not values["username"]:
        if len(values["email"]) > 150:
            raise BootstrapInputError("邮箱超过登录账号长度限制，请用 --username 指定不超过 150 个字符的账号")
        values["username"] = values["email"]
    if values["username"].casefold() == "horilla bot":
        raise BootstrapInputError("该登录账号是系统保留名称，请更换")
    return values


def first_use_progress(facts: Mapping) -> dict:
    """Compute data preparation only; NEVER infer deployment acceptance.

    None means not observable / not permitted, NOT zero or completion.
    The caller reads facts from scoped authority tables; this function cannot
    change facts or mark a step complete.
    """
    scope_ok = facts.get("scope_ok") is True
    specs = [
        ("school", "学校已开户", scope_ok and facts.get("school_count") == 1),
        ("organization", "建立学院、部门与岗位", None if not scope_ok else facts.get("organization_ready")),
        ("staff", "录入第一位真实教职工", None if not scope_ok else facts.get("staff_ready")),
        ("roles", "给日常管理员分配角色", None if not scope_ok else facts.get("roles_ready")),
    ]
    steps = [{"code": code, "title": title,
              "state": "done" if done is True else "unknown" if done is None else "pending"}
             for code, title, done in specs]
    pending = next((s for s in steps if s["state"] != "done"), None)
    state = "BLOCKED" if not scope_ok else "BASIC_DATA_READY" if pending is None else "NEEDS_" + pending["code"].upper()
    return {
        "state": state, "steps": steps,
        "completed": sum(s["state"] == "done" for s in steps), "total": len(steps),
        "next_code": pending["code"] if pending else "acceptance",
        "title": "基础资料已准备，仍需正式业务验收" if pending is None else "下一步：" + pending["title"],
        "production_accepted": False,
        "source": "server_authority_readback",
    }
