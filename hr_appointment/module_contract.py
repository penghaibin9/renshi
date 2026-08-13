"""Machine-readable boundary contract for HR14."""

MODULE_CODE = "HR14"
MODULE_NAME = "岗位聘任"
AUTHORITY_KIND = "position_appointment"
IMPLEMENTATION_STRATEGY = "new"
CANONICAL_API_PREFIX = "/api/v1/hr/appointments"
PERMISSION_PREFIX = "hr.appointment"
CANONICAL_EVENTS = ("PositionAppointmentEffective",)
UPSTREAM_AUTHORITIES = ("HR02", "HR03", "HR12", "HR13")
DOWNSTREAM_CONSUMERS = ("HR03", "HR15", "HR16", "HR17", "HR18")
LEGACY_TECH_SOURCES = ("employee", "pms", "notifications", "horilla_audit")
