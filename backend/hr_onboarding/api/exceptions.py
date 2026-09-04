"""
hr_onboarding/api/exceptions.py

HR05 API 异常与错误码（总册 §35 + 00 §29 错误信封继承）。

写 API 冲突码：
- 409 INVALID_STATE_TRANSITION
- 409 VERSION_CONFLICT
- 409 ONBOARDING_CASE_DUPLICATE
- 409 POSITION_RESERVATION_INVALID
- 409 PERSON_MATCH_CONFLICT
- 409 TASK_ALREADY_COMPLETED
- 409 PROBATION_ALREADY_FINALIZED

公共/权限：
- 403 TENANT_CONTEXT_REQUIRED
- 403 PERMISSION_DENIED
"""


class Hr05ApiError(Exception):
    """HR05 API 业务异常基类。"""

    status_code = 400
    code = "HR05_API_ERROR"
    retryable = False

    def __init__(self, message: str, details: dict | None = None):
        self.message = message
        self.details = details or {}
        super().__init__(message)


class TenantContextRequiredError(Hr05ApiError):
    status_code = 403
    code = "TENANT_CONTEXT_REQUIRED"

    def __init__(self, message: str = "请选择当前学校（多学校账号需明确学校上下文）"):
        super().__init__(message)


class PermissionDeniedError(Hr05ApiError):
    status_code = 403
    code = "PERMISSION_DENIED"


class NotFoundError(Hr05ApiError):
    status_code = 404
    code = "NOT_FOUND"


class VersionConflictError(Hr05ApiError):
    status_code = 409
    code = "VERSION_CONFLICT"


class InvalidStateTransitionError(Hr05ApiError):
    status_code = 409
    code = "INVALID_STATE_TRANSITION"


class OnboardingCaseInvalidSourceError(Hr05ApiError):
    status_code = 422
    code = "ONBOARDING_CASE_INVALID_SOURCE"


class OnboardingCaseDuplicateError(Hr05ApiError):
    status_code = 409
    code = "ONBOARDING_CASE_DUPLICATE"


class PositionReservationInvalidError(Hr05ApiError):
    status_code = 409
    code = "POSITION_RESERVATION_INVALID"


class PersonMatchRequiredError(Hr05ApiError):
    status_code = 409
    code = "PERSON_MATCH_REQUIRED"


class PersonMatchConflictError(Hr05ApiError):
    status_code = 409
    code = "PERSON_MATCH_CONFLICT"


class BlockingMaterialMissingError(Hr05ApiError):
    status_code = 422
    code = "BLOCKING_MATERIAL_MISSING"


class MaterialNotVerifiedError(Hr05ApiError):
    status_code = 422
    code = "MATERIAL_NOT_VERIFIED"


class MaterialDownloadTicketError(Hr05ApiError):
    status_code = 403
    code = "MATERIAL_DOWNLOAD_TICKET_INVALID"


class MaterialDownloadAuditUnavailableError(Hr05ApiError):
    status_code = 503
    code = "MATERIAL_DOWNLOAD_AUDIT_UNAVAILABLE"
    retryable = True


class ActivationAlreadyCompletedError(Hr05ApiError):
    status_code = 409
    code = "ACTIVATION_ALREADY_COMPLETED"


class ActivationPartialFailureError(Hr05ApiError):
    status_code = 200  # 核心 HR 激活成功、外部 provisioning 部分失败时返回部分状态
    code = "ACTIVATION_PARTIAL_FAILURE"
    retryable = True


class StaffNumberConflictError(Hr05ApiError):
    status_code = 409
    code = "STAFF_NUMBER_CONFLICT"


class TaskPrerequisiteNotMetError(Hr05ApiError):
    status_code = 422
    code = "TASK_PREREQUISITE_NOT_MET"


class TaskAlreadyCompletedError(Hr05ApiError):
    status_code = 409
    code = "TASK_ALREADY_COMPLETED"


class PortalTokenExpiredError(Hr05ApiError):
    status_code = 401
    code = "PORTAL_TOKEN_EXPIRED"

    def __init__(self, message: str = "门户访问令牌已过期"):
        super().__init__(message)


class PortalTokenRevokedError(Hr05ApiError):
    status_code = 401
    code = "PORTAL_TOKEN_REVOKED"

    def __init__(self, message: str = "门户访问令牌已撤销"):
        super().__init__(message)


class ProbationAlreadyFinalizedError(Hr05ApiError):
    status_code = 409
    code = "PROBATION_ALREADY_FINALIZED"


class IdempotencyReplayError(Hr05ApiError):
    status_code = 200  # 幂等重放返回原结果，不视为错误
    code = "IDEMPOTENT_REPLAY"


class IdempotencyConflictError(Hr05ApiError):
    """The same scoped key was reused for a different command payload."""

    status_code = 409
    code = "IDEMPOTENCY_KEY_CONFLICT"


class IdempotencyInProgressError(Hr05ApiError):
    """Another worker still owns the live command lease."""

    status_code = 409
    code = "IDEMPOTENCY_IN_PROGRESS"
    retryable = True
