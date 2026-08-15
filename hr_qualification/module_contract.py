"""Machine-readable boundary contract for HR09."""

MODULE_CODE = "HR09"
MODULE_NAME = "教师资格与双师型"
APP_LABEL = "hr_qualification"
AUTHORITY_KIND = "qualification_and_dual_teacher_recognition"
IMPLEMENTATION_STRATEGY = "new"
CANONICAL_API_PREFIX = "/api/v1/hr/qualifications"
PERMISSION_PREFIX = "hr.qualification"
UPSTREAM_AUTHORITIES = ("HR03", "HR08", "HR10", "HR12")
DOWNSTREAM_CONSUMERS = ("HR10", "HR13", "HR14", "HR17", "HR18")
OWNS = (
    "教师资格与职业资格核验事实",
    "双师型规则版本、申报证据包与认定结果",
    "双师型认定有效期、复核、升级、降级与撤销历史",
)
FORBIDDEN_DIRECT_WRITES = (
    "HR03 人员主档与任职事实",
    "HR10 培训及企业实践事实",
    "HR13 专业技术职务事实",
)
