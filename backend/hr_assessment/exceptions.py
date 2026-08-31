"""HR12 Assessment — 服务层基础异常（S1.4）。"""


class AssessmentError(Exception):
    """HR12 域通用异常。"""

    code: str
    message: str
    retryable: bool = False
    http_status: int = 400

    def __init__(self, code: str, message: str, retryable: bool = False, http_status: int = 400):
        self.code = code
        self.message = message
        self.retryable = retryable
        self.http_status = http_status
        super().__init__(message)


class AssessmentPolicyNotFoundError(AssessmentError):
    def __init__(self, message: str = "考核政策未找到"):
        super().__init__(code="ASSESSMENT_POLICY_NOT_FOUND", message=message, http_status=404)


class AssessmentPolicyAmbiguousError(AssessmentError):
    def __init__(self, message: str = "考核政策不唯一"):
        super().__init__(code="ASSESSMENT_POLICY_AMBIGUOUS", message=message, http_status=409)


class AssessmentCycleClosedError(AssessmentError):
    def __init__(self, message: str = "考核周期已关闭"):
        super().__init__(code="ASSESSMENT_CYCLE_CLOSED", message=message, http_status=409)


class AssessmentSubjectIneligibleError(AssessmentError):
    def __init__(self, message: str = "人员不在考核范围"):
        super().__init__(code="ASSESSMENT_SUBJECT_INELIGIBLE", message=message, http_status=422)


class AssessmentReviewerConflictError(AssessmentError):
    def __init__(self, message: str = "评议人存在利益冲突"):
        super().__init__(code="ASSESSMENT_REVIEWER_CONFLICT", message=message, http_status=409)


class AssessmentGatewayBlockedError(AssessmentError):
    def __init__(self, message: str = "硬门槛未通过"):
        super().__init__(code="ASSESSMENT_GATE_BLOCKED", message=message, http_status=422)


class AssessmentAlreadyFinalizedError(AssessmentError):
    def __init__(self, message: str = "考核结果已审定，不可修改"):
        super().__init__(code="ASSESSMENT_ALREADY_FINALIZED", message=message, http_status=409)


class AssessmentProviderUnavailableError(AssessmentError):
    def __init__(self, provider: str = ""):
        msg = f"数据源不可用: {provider}" if provider else "数据源不可用"
        super().__init__(code="ASSESSMENT_PROVIDER_UNAVAILABLE", message=msg, http_status=503, retryable=True)


class TenantRequiredError(AssessmentError):
    def __init__(self, message: str = "缺少租户上下文"):
        super().__init__(code="TENANT_REQUIRED", message=message, http_status=403)
