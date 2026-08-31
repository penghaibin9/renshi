"""
hr_recruitment/api/exceptions.py

HR04 API 异常与错误码（总册 17.2/17.3 + HR01 错误信封继承）。

写 API 冲突码：
- 409 VERSION_CONFLICT
- 409 POSITION_CAPACITY_CONFLICT
- 409 INVALID_STATE_TRANSITION
- 409 SCORE_ALREADY_LOCKED
- 409 APPLICATION_ALREADY_SUBMITTED

公共/权限：
- 403 TENANT_CONTEXT_REQUIRED
- 403 PERMISSION_DENIED
"""


class Hr04ApiError(Exception):
    """HR04 API 业务异常基类。"""

    status_code = 400
    code = "HR04_API_ERROR"

    def __init__(self, message: str, details: dict | None = None, status_code: int | None = None):
        self.message = message
        self.details = details or {}
        if status_code is not None:
            self.status_code = status_code
        super().__init__(message)


class TenantContextRequiredError(Hr04ApiError):
    status_code = 403
    code = "TENANT_CONTEXT_REQUIRED"

    def __init__(self, message: str = "请选择当前学校（多学校账号需明确学校上下文）"):
        super().__init__(message)


class PermissionDeniedError(Hr04ApiError):
    status_code = 403
    code = "PERMISSION_DENIED"


class NotFoundError(Hr04ApiError):
    status_code = 404
    code = "NOT_FOUND"


class VersionConflictError(Hr04ApiError):
    status_code = 409
    code = "VERSION_CONFLICT"


class PositionCapacityConflictError(Hr04ApiError):
    status_code = 409
    code = "POSITION_CAPACITY_CONFLICT"


class InvalidStateTransitionError(Hr04ApiError):
    status_code = 409
    code = "INVALID_STATE_TRANSITION"


class ScoreAlreadyLockedError(Hr04ApiError):
    status_code = 409
    code = "SCORE_ALREADY_LOCKED"


class ApplicationAlreadySubmittedError(Hr04ApiError):
    status_code = 409
    code = "APPLICATION_ALREADY_SUBMITTED"


class IdempotencyReplayError(Hr04ApiError):
    status_code = 200  # 幂等重放返回原结果，不视为错误
    code = "IDEMPOTENT_REPLAY"


class QualificationRuleVersionMismatchError(Hr04ApiError):
    status_code = 409
    code = "QUALIFICATION_RULE_VERSION_MISMATCH"


class HandoffPreconditionError(Hr04ApiError):
    status_code = 422
    code = "HANDOFF_PRECONDITION_FAILED"
