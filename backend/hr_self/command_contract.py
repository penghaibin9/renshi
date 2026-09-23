"""Strict SELF command boundary. No Django imports, no client identity trust."""
import hashlib
import json
import re

IDENTITY_KEYS = frozenset({"tenantId", "tenant_id", "companyId", "company_id", "staffId", "staff_id", "personId", "person_id", "employeeId", "employee_id", "userId", "user_id", "actorId", "actor_id", "scope_type", "scope_id", "staff_ids"})
SELF_FIELDS = {"person.legal_name": "姓名更正", "person.gender_code": "性别信息更正", "person.birth_date": "出生日期更正", "contact.mobile": "联系电话更正", "contact.personal_email": "个人邮箱更正"}
class CommandError(ValueError):
    def __init__(self, code, message, status=400):
        self.code, self.status = code, status
        super().__init__(message)

def check_object(value, allowed):
    if not isinstance(value, dict):
        raise CommandError("OBJECT_REQUIRED", "请求必须是JSON对象")
    if set(value) & IDENTITY_KEYS:
        raise CommandError("SELF_IDENTITY_OVERRIDE_FORBIDDEN", "本人身份只能由当前登录和学校确定", 403)
    if set(value) - set(allowed):
        raise CommandError("UNKNOWN_FIELDS", "请求包含未开放字段")
    return value

def expected_version(value):
    if type(value) is not int or value < 1:
        raise CommandError("EXPECTED_VERSION_REQUIRED", "须提供页面读取的有效版本号")
    return value

def idempotency_key(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{8,128}", value):
        raise CommandError("IDEMPOTENCY_KEY_REQUIRED", "须提供8至128位请求编号")
    return value

def command_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
