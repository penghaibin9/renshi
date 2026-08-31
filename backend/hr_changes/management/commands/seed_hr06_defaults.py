"""
hr_changes/management/commands/seed_hr06_defaults.py

HR06 默认字典种子（幂等）：
- 16 个 ChangeAction（总册 §7 + CHANGE_ACTION_MATRIX）
- 每动作默认 Reason（总册 §8 + CHANGE_ACTION_MATRIX §2）
- 受管字段定义（总册 §57 + LegacyChangeMapping §1）

用法：python manage.py seed_hr06_defaults --tenant=1
"""

from django.core.management.base import BaseCommand

from hr_changes.models import HrChangeAction, HrChangeFieldDefinition, HrChangeReason

# (code, name, is_temporary, reporting_manager_policy, allowed_initiators)
ACTIONS = [
    ("ORG_TRANSFER", "组织调动", False, "DERIVE_FROM_TARGET_ORG",
     ["SELF", "REPORTING_MANAGER", "COLLEGE_HR", "TARGET_ORG", "SCHOOL_HR", "RESTRUCTURE_ADMIN"]),
    ("POSITION_TRANSFER", "岗位调动", False, "DERIVE_FROM_TARGET_ORG",
     ["SELF", "REPORTING_MANAGER", "COLLEGE_HR", "TARGET_ORG", "SCHOOL_HR", "RESTRUCTURE_ADMIN"]),
    ("ORG_POSITION_TRANSFER", "组织+岗位调动", False, "DERIVE_FROM_TARGET_ORG",
     ["SELF", "REPORTING_MANAGER", "COLLEGE_HR", "TARGET_ORG", "SCHOOL_HR", "RESTRUCTURE_ADMIN"]),
    ("POST_CATEGORY_CHANGE", "岗位类别变更", False, "KEEP",
     ["COLLEGE_HR", "TARGET_ORG", "SCHOOL_HR"]),
    ("EMPLOYEE_CATEGORY_CHANGE", "人员类别变更", False, "KEEP",
     ["COLLEGE_HR", "TARGET_ORG", "SCHOOL_HR"]),
    ("EMPLOYMENT_TYPE_CHANGE", "用工性质变更", False, "KEEP",
     ["SCHOOL_HR"]),
    ("MANAGER_CHANGE", "直属上级变更", False, "SELECT_EXPLICIT",
     ["REPORTING_MANAGER", "COLLEGE_HR", "TARGET_ORG", "SCHOOL_HR"]),
    ("LOCATION_CHANGE", "工作地点变更", False, "KEEP",
     ["REPORTING_MANAGER", "COLLEGE_HR", "SCHOOL_HR"]),
    ("ADD_SECONDARY_ASSIGNMENT", "增加兼岗", False, "KEEP",
     ["SELF", "REPORTING_MANAGER", "COLLEGE_HR", "TARGET_ORG", "SCHOOL_HR"]),
    ("END_SECONDARY_ASSIGNMENT", "取消兼岗", False, "KEEP",
     ["SELF", "REPORTING_MANAGER", "COLLEGE_HR", "TARGET_ORG", "SCHOOL_HR"]),
    ("PRIMARY_ASSIGNMENT_SWITCH", "主岗切换", False, "KEEP",
     ["REPORTING_MANAGER", "COLLEGE_HR", "SCHOOL_HR"]),
    ("TEMPORARY_SECONDMENT", "借调", True, "KEEP",
     ["SELF", "REPORTING_MANAGER", "COLLEGE_HR", "TARGET_ORG", "SCHOOL_HR"]),
    ("TEMPORARY_ATTACHMENT", "挂职", True, "KEEP",
     ["SELF", "REPORTING_MANAGER", "COLLEGE_HR", "TARGET_ORG", "SCHOOL_HR"]),
    ("RETURN_FROM_TEMPORARY", "返岗", True, "KEEP",
     ["SELF", "REPORTING_MANAGER", "COLLEGE_HR", "TARGET_ORG", "SCHOOL_HR"]),
    ("BULK_ORG_RESTRUCTURE_MOVE", "批量组织调整", False, "DERIVE_FROM_TARGET_ORG",
     ["RESTRUCTURE_ADMIN"]),
    ("DATA_CORRECTION", "数据纠错", False, "KEEP",
     ["SCHOOL_HR"]),
]

# (action_code, code, name, requires_document)
REASONS = {
    "ORG_TRANSFER": [
        ("SCHOOL_ORG_OPTIMIZATION", "学校组织优化", False),
        ("PERSONAL_APPLICATION", "个人申请", True),
        ("WORK_NEED", "工作需要", True),
        ("ORGANIZATION_RESTRUCTURE", "组织重组", False),
    ],
    "POSITION_TRANSFER": [
        ("WORK_NEED", "工作需要", True),
        ("PERSONAL_APPLICATION", "个人申请", True),
        ("POSITION_RESTRUCTURE", "岗位调整", False),
    ],
    "ORG_POSITION_TRANSFER": [
        ("WORK_NEED", "工作需要", True),
        ("PERSONAL_APPLICATION", "个人申请", True),
        ("ORGANIZATION_RESTRUCTURE", "组织重组", False),
    ],
    "POST_CATEGORY_CHANGE": [
        ("PROFESSIONAL_TO_ADMIN", "专技转管理", True),
        ("ADMIN_TO_PROFESSIONAL", "管理转专技", True),
        ("WORK_NEED", "工作需要", True),
    ],
    "EMPLOYEE_CATEGORY_CHANGE": [
        ("CATEGORY_RECLASSIFICATION", "类别重新认定", True),
        ("WORK_NEED", "工作需要", True),
    ],
    "EMPLOYMENT_TYPE_CHANGE": [
        ("LABOR_CONTRACT_CHANGE", "合同用工变化", True),
        ("POLICY_ADJUSTMENT", "政策调整", False),
    ],
    "MANAGER_CHANGE": [
        ("ORG_REORGANIZATION", "组织调整", False),
        ("WORK_NEED", "工作需要", True),
    ],
    "LOCATION_CHANGE": [
        ("ORG_MOVE", "单位搬迁", False),
        ("CAMPUS_ADJUSTMENT", "校区调整", False),
    ],
    "ADD_SECONDARY_ASSIGNMENT": [
        ("WORK_NEED", "工作需要", True),
        ("TALENT_DEVELOPMENT", "人才培养", True),
    ],
    "END_SECONDARY_ASSIGNMENT": [
        ("WORK_NEED", "工作需要", True),
        ("PROJECT_END", "项目结束", False),
    ],
    "PRIMARY_ASSIGNMENT_SWITCH": [
        ("WORK_NEED", "工作需要", True),
        ("ORG_REORGANIZATION", "组织调整", False),
    ],
    "TEMPORARY_SECONDMENT": [
        ("PROJECT_SUPPORT", "项目支援", True),
        ("HIGHER_AUTHORITY_ASSIGNMENT", "上级部门借调", True),
    ],
    "TEMPORARY_ATTACHMENT": [
        ("PROJECT_SUPPORT", "项目支援", True),
        ("HIGHER_AUTHORITY_ASSIGNMENT", "上级部门挂职", True),
        ("TALENT_DEVELOPMENT", "人才培养", True),
    ],
    "RETURN_FROM_TEMPORARY": [
        ("TEMPORARY_PERIOD_END", "借调期满", False),
        ("EARLY_RETURN", "提前返岗", True),
    ],
    "BULK_ORG_RESTRUCTURE_MOVE": [
        ("ORGANIZATION_RESTRUCTURE", "组织重组", False),
    ],
    "DATA_CORRECTION": [
        ("DATA_ENTRY_ERROR", "录入错误", False),
        ("SOURCE_DOCUMENT_REVISION", "依据材料修订", True),
    ],
}

# (domain, field_code, label, legacy_field, authority_source, edit_mode)
FIELD_DEFINITIONS = [
    ("assignment", "organization", "所属单位", "EmployeeWorkInformation.department_id",
     "hr03.HrStaffAssignment.organization_id", "CHANGE_CASE_ONLY"),
    ("assignment", "position", "岗位", "EmployeeWorkInformation.job_position_id",
     "hr03.HrStaffAssignment.position_id", "CHANGE_CASE_ONLY"),
    ("assignment", "post_catalog", "岗位类别", "EmployeeWorkInformation.job_role_id",
     "hr03.HrStaffAssignment.post_catalog_id", "CHANGE_CASE_ONLY"),
    ("assignment", "reporting_staff", "直属上级", "EmployeeWorkInformation.reporting_manager_id",
     "hr03.HrStaffAssignment.reporting_staff_id", "CHANGE_CASE_ONLY"),
    ("assignment", "fte", "工作量（FTE）", "（无 legacy）",
     "hr03.HrStaffAssignment.fte", "CHANGE_CASE_ONLY"),
    ("assignment", "location", "工作地点", "EmployeeWorkInformation.location",
     "hr03.HrStaffAssignment.location（V1 映射列）", "CHANGE_CASE_ONLY"),
    ("relationship", "relationship_type", "用工性质", "EmployeeWorkInformation.employee_type_id",
     "hr03.HrEmploymentRelationship.relationship_type", "CHANGE_CASE_ONLY"),
    ("relationship", "employment_type", "聘用方式", "（无 legacy）",
     "hr03.HrEmploymentRelationship.employment_type", "CHANGE_CASE_ONLY"),
    ("staff", "staff_category_code", "人员类别", "（无 legacy）",
     "hr03.HrStaffMaster.staff_category_code", "CHANGE_CASE_ONLY"),
]


class Command(BaseCommand):
    help = "Seed HR06 default actions/reasons/field definitions (idempotent, per tenant)"

    def add_arguments(self, parser):
        parser.add_argument("--tenant", type=int, required=True, help="tenant_id")

    def handle(self, *args, **options):
        tenant_id = options["tenant"]
        created = {"actions": 0, "reasons": 0, "fields": 0}

        for code, name, is_temp, rm_policy, initiators in ACTIONS:
            _, was = HrChangeAction.objects.get_or_create(
                tenant_id=tenant_id,
                code=code,
                defaults={
                    "name": name,
                    "is_temporary": is_temp,
                    "reporting_manager_policy": rm_policy,
                    "allowed_initiators_json": initiators,
                },
            )
            if was:
                created["actions"] += 1

        for action_code, reasons in REASONS.items():
            for rcode, rname, req_doc in reasons:
                _, was = HrChangeReason.objects.get_or_create(
                    tenant_id=tenant_id,
                    action_code=action_code,
                    code=rcode,
                    defaults={
                        "name": rname,
                        "requires_document": req_doc,
                    },
                )
                if was:
                    created["reasons"] += 1

        for domain, fcode, label, legacy, authority, mode in FIELD_DEFINITIONS:
            _, was = HrChangeFieldDefinition.objects.get_or_create(
                tenant_id=tenant_id,
                domain=domain,
                field_code=fcode,
                defaults={
                    "label": label,
                    "legacy_field": legacy,
                    "authority_source": authority,
                    "edit_mode": mode,
                },
            )
            if was:
                created["fields"] += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"tenant={tenant_id} created: actions={created['actions']} "
                f"reasons={created['reasons']} fields={created['fields']}"
            )
        )
