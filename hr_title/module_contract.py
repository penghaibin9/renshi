"""Machine-readable boundary contract for HR13.

Global registries and tests should import this module instead of duplicating
HR13 ownership/API/permission metadata in unrelated apps.
"""

MODULE_CODE = "HR13"
MODULE_NAME = "职称评审"
AUTHORITY_KIND = "evaluation_decision"
IMPLEMENTATION_STRATEGY = "new"
CANONICAL_API_PREFIX = "/api/v1/hr/titles"
PERMISSION_PREFIX = "hr.title"
CANONICAL_EVENTS = (
    "ProfessionalTitleResultEffective",
    "ProfessionalTitleResultRevised",
    "ProfessionalTitleResultRevoked",
)
UPSTREAM_AUTHORITIES = ("HR03", "HR09", "HR10", "HR12")
DOWNSTREAM_CONSUMERS = ("HR14", "HR15", "HR17", "HR18")
LEGACY_TECH_SOURCES = ("employee", "notifications", "horilla_audit", "pms")
