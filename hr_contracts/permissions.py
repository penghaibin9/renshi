"""HR07 canonical permission contract."""

from django.core.exceptions import PermissionDenied

from horilla.hr_permission_registry import PermissionDefinition, register_permissions

PERM_AGREEMENT_VIEW = "hr.contracts.agreement.view"
PERM_AGREEMENT_CREATE = "hr.contracts.agreement.create"
PERM_AGREEMENT_SIGN = "hr.contracts.agreement.sign"
PERM_AGREEMENT_ACTIVATE = "hr.contracts.agreement.activate"

PERM_CASE_CREATE = "hr.contracts.case.create"
PERM_CASE_SUBMIT = "hr.contracts.case.submit"
PERM_CASE_APPROVE = "hr.contracts.case.approve"
PERM_CASE_SIGN = "hr.contracts.case.sign"
PERM_CASE_ACTIVATE = "hr.contracts.case.activate"
PERM_CASE_TERMINATE = "hr.contracts.case.terminate"

PERMISSION_DEFINITIONS = (
    PermissionDefinition(PERM_AGREEMENT_VIEW, "HR07", "查看学校合同主档及正式版本"),
    PermissionDefinition(PERM_AGREEMENT_CREATE, "HR07", "创建合同主档"),
    PermissionDefinition(PERM_AGREEMENT_SIGN, "HR07", "冻结首个签署版本"),
    PermissionDefinition(PERM_AGREEMENT_ACTIVATE, "HR07", "使已签署版本正式生效"),
    PermissionDefinition(PERM_CASE_CREATE, "HR07", "发起合同续签、变更或解除业务单"),
    PermissionDefinition(PERM_CASE_SUBMIT, "HR07", "提交合同续签、变更或解除业务单"),
    PermissionDefinition(PERM_CASE_APPROVE, "HR07", "审批合同续签、变更或解除业务单"),
    PermissionDefinition(PERM_CASE_SIGN, "HR07", "冻结续签或变更后的新合同版本"),
    PermissionDefinition(PERM_CASE_ACTIVATE, "HR07", "使续签或变更后的新合同版本生效"),
    PermissionDefinition(PERM_CASE_TERMINATE, "HR07", "执行已批准合同解除生效"),
)
register_permissions(PERMISSION_DEFINITIONS)


def enforce_contract_permission(request, permission_code: str) -> None:
    """Fail closed for unauthenticated or ungranted HR07 requests."""
    user = getattr(request, "user", None)
    if user is None or not getattr(user, "is_authenticated", False):
        raise PermissionDenied("UNAUTHENTICATED")
    if not (getattr(user, "is_superuser", False) or user.has_perm(permission_code)):
        raise PermissionDenied("PERMISSION_DENIED")
