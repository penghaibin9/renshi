"""
hr_control_center/selectors/workforce.py

WorkforceSelector —— HR01-04 队伍结构只读查询。

接受已解析的 HrRequestContext，返回 domain DTO（不含 HTTP/渲染层合同，不 render HTML）。
- 小样本隐私（总册 12.5）：非 HR 管理员（superuser 或拥有 workforce.drilldown 权限）
  的聚合小组人数 < PRIVACY_MASK_THRESHOLD 时显示 "<5"。
- 学历/职称/双师无权威事实 → 直接标记 UNAVAILABLE，不伪造结构。
- 所有分组基于 provider 的固定维度方法，禁止任意 group_by。
"""

from __future__ import annotations

from django.contrib.auth import get_user_model

from hr_control_center.context import HrRequestContext
from hr_control_center.providers.workforce import LegacyWorkforceProvider
from hr_control_center.services.metric_registry import (
    ERROR,
    OK,
    PARTIAL,
    STALE,
    UNAVAILABLE,
)

# 小样本隐私阈值（总册 12.5，可配置）
PRIVACY_MASK_THRESHOLD = 5

# 分布维度白名单（总册 12.6：禁止任意 group_by）
DISTRIBUTION_DIMENSIONS = frozenset(
    {
        "personnel_category",
        "department",
        "job_position",
        "gender",
        "age_group",
    }
)

# 维度 → provider 方法名
_DISTRIBUTION_METHODS = {
    "personnel_category": "distribution_by_employee_type",
    "department": "distribution_by_department",
    "job_position": "distribution_by_job_position",
    "gender": "distribution_by_gender",
    "age_group": "distribution_by_age_group",
}

# Legacy 阶段无权威事实的维度 → UNAVAILABLE（reasonCode, message）
_UNAVAILABLE_DIMENSIONS = {
    "education": (
        "EDUCATION_FACT_MISSING",
        "学历学位需结构化权威事实（HR05/06），Employee.qualification 为单一自由文本，"
        "禁止用于结构化学历分布。",
    ),
    "title": (
        "TITLE_FACT_MISSING",
        "职称需权威聘任事实（HR07），Legacy 快照无职称字段。",
    ),
    "doubleTeacher": (
        "MODULE_NOT_AVAILABLE",
        "双师型教师模块（HR09）尚未建设。",
    ),
}


class WorkforceSelector:
    """队伍结构只读查询，返回 domain DTO。"""

    def __init__(self, context: HrRequestContext, provider=None):
        self.context = context
        self.provider = provider or LegacyWorkforceProvider()

    # ---- 小样本隐私 -------------------------------------------------------

    def _is_hr_admin(self) -> bool:
        """HR 管理员（superuser 或拥有 workforce.drilldown）不受小样本脱敏限制。"""
        if not self.context.user_id:
            return False
        try:
            user = get_user_model().objects.filter(pk=self.context.user_id).first()
        except Exception:
            return False
        if user is None:
            return False
        if user.is_superuser:
            return True
        return user.has_perm("hr.dashboard.workforce.drilldown")

    def _mask(self, value):
        """小组人数脱敏：非管理员且人数 < 阈值 → "<5"。"""
        if self._is_hr_admin():
            return value
        if value is None:
            return None
        return "<5" if value < PRIVACY_MASK_THRESHOLD else value

    def _masked_buckets(self, data):
        return [self._mask_bucket(b) for b in data.get("buckets", [])]

    def _mask_bucket(self, bucket):
        return {**bucket, "count": self._mask(bucket["count"])}

    # ---- 内部工具 ---------------------------------------------------------

    @staticmethod
    def _result_meta(*results):
        computed = max(
            (r.computed_at for r in results if r.computed_at), default=None
        )
        updated = max(
            (r.source_updated_at for r in results if r.source_updated_at), default=None
        )
        return {
            "computedAt": computed.isoformat() if computed else None,
            "sourceUpdatedAt": updated.isoformat() if updated else None,
        }

    @staticmethod
    def _unavailable_section(reason_code, message):
        return {"status": UNAVAILABLE, "reasonCode": reason_code, "message": message}

    def _distribution_section(self, result, interpretation=None, note=None):
        if result.status != OK:
            return {
                "status": result.status,
                "reasonCode": result.reason_code,
                "message": result.message,
            }
        section = {"status": OK, "buckets": self._masked_buckets(result.data)}
        if interpretation:
            section["interpretation"] = interpretation
        if note:
            section["note"] = note
        return section

    @staticmethod
    def _aggregate_status(sections) -> str:
        statuses = [s["status"] for s in sections.values()]
        if any(st == ERROR for st in statuses):
            return ERROR
        if any(st == UNAVAILABLE for st in statuses):
            return PARTIAL
        if any(st == STALE for st in statuses):
            return STALE
        return OK

    # ---- DTO --------------------------------------------------------------

    def summary(self) -> dict:
        """
        队伍结构结论卡 DTO。

        sections：headcount / personnelCategory / fullTimeTeacher / department /
                  jobPosition / gender / ageGroup / education / title / doubleTeacher
        conclusions：供结论卡直接渲染的 key-label-status 列表。
        """
        ctx = self.context
        headcount_result = self.provider.active_headcount(ctx)
        personnel_result = self.provider.distribution_by_employee_type(ctx)
        dept_result = self.provider.distribution_by_department(ctx)
        position_result = self.provider.distribution_by_job_position(ctx)
        gender_result = self.provider.distribution_by_gender(ctx)
        age_result = self.provider.distribution_by_age_group(ctx)

        results = [
            headcount_result,
            personnel_result,
            dept_result,
            position_result,
            gender_result,
            age_result,
        ]

        headcount_section = (
            {"status": OK, "value": headcount_result.data["value"]}
            if headcount_result.status == OK
            else {
                "status": headcount_result.status,
                "reasonCode": headcount_result.reason_code,
                "message": headcount_result.message,
            }
        )

        sections = {
            "headcount": headcount_section,
            "personnelCategory": self._distribution_section(
                personnel_result,
                interpretation="RAW_EMPLOYEE_TYPE",
                note="employee_type 为 Horilla 自由文本字典，不等同高校人员类别权威字典"
                "（专任教师等口径需 HR03）。",
            ),
            "fullTimeTeacher": self._unavailable_section(
                "PERSONNEL_CATEGORY_DICT_MISSING",
                "专任教师口径依赖 HR03 人员类别权威字典，Legacy 快照无法可靠判定。",
            ),
            "department": self._distribution_section(dept_result),
            "jobPosition": self._distribution_section(position_result),
            "gender": self._distribution_section(gender_result),
            "ageGroup": self._distribution_section(age_result),
        }
        for key, (reason_code, message) in _UNAVAILABLE_DIMENSIONS.items():
            sections[key] = self._unavailable_section(reason_code, message)

        conclusions = [
            {
                "key": "headcount",
                "label": "在岗教职工",
                "status": headcount_section["status"],
                "value": headcount_section.get("value"),
                "unit": "人",
            },
            {
                "key": "fullTimeTeacher",
                "label": "专任教师",
                "status": sections["fullTimeTeacher"]["status"],
                "reasonCode": sections["fullTimeTeacher"]["reasonCode"],
                "message": sections["fullTimeTeacher"]["message"],
            },
            {
                "key": "personnelCategory",
                "label": "人员类别（employee_type 原始口径）",
                "status": sections["personnelCategory"]["status"],
                "note": sections["personnelCategory"].get("note"),
            },
            {
                "key": "department",
                "label": "当前组织（部门）",
                "status": sections["department"]["status"],
            },
            {
                "key": "jobPosition",
                "label": "当前岗位",
                "status": sections["jobPosition"]["status"],
            },
            {"key": "gender", "label": "性别结构", "status": sections["gender"]["status"]},
            {
                "key": "ageGroup",
                "label": "年龄结构",
                "status": sections["ageGroup"]["status"],
            },
            {
                "key": "education",
                "label": "学历学位",
                "status": sections["education"]["status"],
                "reasonCode": sections["education"]["reasonCode"],
                "message": sections["education"]["message"],
            },
            {
                "key": "title",
                "label": "职称",
                "status": sections["title"]["status"],
                "reasonCode": sections["title"]["reasonCode"],
                "message": sections["title"]["message"],
            },
            {
                "key": "doubleTeacher",
                "label": "双师型",
                "status": sections["doubleTeacher"]["status"],
                "reasonCode": sections["doubleTeacher"]["reasonCode"],
                "message": sections["doubleTeacher"]["message"],
            },
        ]

        return {
            "status": self._aggregate_status(sections),
            **self._result_meta(*results),
            "sections": sections,
            "conclusions": conclusions,
        }

    def distribution(self, dimension: str) -> dict:
        """按维度分布 DTO。dimension 必须属于白名单，否则返回 INVALID_DIMENSION。"""
        if dimension not in DISTRIBUTION_DIMENSIONS:
            return {
                "status": UNAVAILABLE,
                "reasonCode": "INVALID_DIMENSION",
                "message": f"非法维度: {dimension}，允许的维度: {sorted(DISTRIBUTION_DIMENSIONS)}",
            }
        # department 维度优先 HR02 权威组织（总册 1.3）；HR02 未就绪 → UNAVAILABLE，不 fallback legacy
        if dimension == "department":
            result = self.provider.distribution_by_hr02_org(self.context)
        else:
            result = getattr(self.provider, _DISTRIBUTION_METHODS[dimension])(self.context)
        if result.status != OK:
            return {
                "status": result.status,
                **self._result_meta(result),
                "reasonCode": result.reason_code,
                "message": result.message,
            }
        data = result.data
        dto = {
            "status": OK,
            **self._result_meta(result),
            "dimension": data.get("dimension", dimension),
            "buckets": self._masked_buckets(data),
            "total": data.get("total"),
        }
        if data.get("interpretation"):
            dto["interpretation"] = data["interpretation"]
        if dimension == "personnel_category":
            dto["note"] = (
                "employee_type 为 Horilla 自由文本字典，不等同高校人员类别权威字典"
                "（专任教师等口径需 HR03）。"
            )
        return dto

    def org_comparison(self) -> dict:
        """学院/部门对比宽表 DTO。Legacy 阶段组织以 Department 为准。"""
        result = self.provider.org_comparison(self.context)
        if result.status != OK:
            return {
                "status": result.status,
                **self._result_meta(result),
                "reasonCode": result.reason_code,
                "message": result.message,
                "rows": [],
                "total": None,
            }
        data = result.data
        rows = [
            {
                "departmentId": row["departmentId"],
                "department": row["department"],
                "headcount": row["headcount"],
                "gender": [self._mask_bucket(b) for b in row["gender"]],
                "employeeType": [self._mask_bucket(b) for b in row["employeeType"]],
                "ageGroup": [self._mask_bucket(b) for b in row["ageGroup"]],
            }
            for row in data["rows"]
        ]
        return {
            "status": OK,
            **self._result_meta(result),
            "rows": rows,
            "total": data["total"],
        }
