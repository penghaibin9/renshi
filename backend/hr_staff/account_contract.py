"""HR03 account activation contract.

Account lifecycle is intentionally separate from HrStaffMaster facts.  These
constants are shared by the administrator API, invitation service and tests so
the security-sensitive strings are not scattered across the module.
"""

ACCOUNT_MANAGE_PERMISSION = "hr.staff.account.manage"
SELF_PERMISSION = "hr.self.view"
SYSTEM_SELF_GROUP = "__system_hr17_self__"
INVITATION_TOKEN_NAMESPACE = "hr-account-invitation"
INVITATION_TTL_HOURS = 24

ACCOUNT_INVITATION_ERRORS = frozenset(
    {
        "ACCOUNT_INVITATION_INVALID",
        "ACCOUNT_INVITATION_EXPIRED",
        "ACCOUNT_INVITATION_REVOKED",
        "ACCOUNT_INVITATION_ACCEPTED",
        "ACCOUNT_INVITATION_EMAIL_REQUIRED",
        "ACCOUNT_INVITATION_CONTACT_CHANGED",
        "ACCOUNT_LINK_EXISTS",
        "ACCOUNT_USERNAME_REQUIRED",
        "ACCOUNT_USERNAME_INVALID",
        "ACCOUNT_USERNAME_TAKEN",
        "ACCOUNT_PASSWORD_INVALID",
        "ACCOUNT_SELF_PERMISSION_MISSING",
        "ACCOUNT_SELF_ROLE_POLICY_INVALID",
    }
)
