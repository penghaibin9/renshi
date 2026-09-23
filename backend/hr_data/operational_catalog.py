"""Versioned school-wide operational indicators. Counts are records, not people.

The catalog does not make current mutable workflows historically reconstructible.
A saved observation is evidence of this collection window, not an arbitrary as-of.
"""
CATALOG_VERSION = "hr18-university-operations/2026-09-14"
CATALOG = (
    ("HR02", "organizations", "组织机构", "hr_structure", "HrOrganization", "identity_status"),
    ("HR02", "staffing_plans", "编制计划", "hr_structure", "HrStaffingPlan", "status"),
    ("HR03", "staff_dossiers", "教职工主档", "hr_staff", "HrStaffMaster", "current_employment_status"),
    ("HR03", "correction_cases", "档案更正申请", "hr_staff", "HrCorrectionCase", "status"),
    ("HR04", "recruitment_offers", "招聘录用通知", "hr_recruitment", "HrRecruitmentOffer", "status"),
    ("HR05", "onboarding_cases", "入职案件", "hr_onboarding", "HrOnboardingCase", "status"),
    ("HR05", "probation_cases", "试用期案件", "hr_onboarding", "HrProbationCase", "status"),
    ("HR06", "personnel_changes", "人事异动案件", "hr_changes", "HrPersonnelChangeCase", "status"),
    ("HR07", "contract_agreements", "合同协议", "hr_contracts", "HrContractAgreement", "status"),
    ("HR08", "external_hiring", "外聘申请", "hr_external", "HrExternalHiringCase", "status"),
    ("HR09", "qualification_credentials", "教师资质记录", "hr_qualification", "HrPersonCredential", "status"),
    ("HR10", "development_plans", "培训进修计划", "hr10_development", "HrDevelopmentPlan", "lifecycle_status"),
    ("HR11", "attendance_days", "考勤日记录（不是教职工人数）", "hr_time", "HrAttendanceDayFact", "status"),
    ("HR12", "assessment_cases", "考核案件", "hr_assessment", "HrAssessmentCase", "status"),
    ("HR13", "title_applications", "职称评审申请", "hr_title", "TitleApplicationCase", "status"),
    ("HR14", "appointment_applications", "岗位聘任申请", "hr_appointment", "AppointmentApplicationCase", "status"),
    ("HR15", "payroll_result_records", "工资结果记录（包含版本，不等于已支付笔数）", "hr_payroll", "PayrollResultFact", "status"),
    ("HR16", "exit_cases", "退休离校案件", "hr_exit", "ExitCase", "status"),
    ("HR16", "flex_retirement_applications", "弹性退休申请（批准不等于退休）", "hr_exit", "RetirementFlexApplication", "status"),
    ("HR03", "material_requests", "本人补件要求（HR03权威）", "hr_staff", "HrMaterialRequest", "status"),
)

def source_result(domain, code, title, *, status, groups=None, error_code=None):
    """No data-source failure may turn into a valid zero."""
    if status == "OK":
        if not isinstance(groups, list) or len(groups) > 64:
            raise ValueError("invalid aggregate groups")
        for row in groups:
            if set(row) != {"state", "count"} or type(row["count"]) is not int or row["count"] < 0:
                raise ValueError("invalid aggregate row")
        value = sum(x["count"] for x in groups)
    else:
        value, groups = None, None
    return {"domain": domain, "code": code, "title": title, "sourceStatus": status,
        "value": value, "unit": "条记录", "byState": groups, "errorCode": error_code,
        "temporalMode": "OBSERVED_WINDOW", "arbitraryHistoricalReconstruction": False}
