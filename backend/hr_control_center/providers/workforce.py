"""
hr_control_center/providers/workforce.py

LegacyWorkforceProvider —— HR01-04 队伍结构在 HR02/HR03 权威模型就绪前的 current-snapshot 数据源。

硬合同（总册 12 / 24 / 31.4 节）：
- dataBasis = LEGACY_CURRENT_SNAPSHOT：只反映“当前 as_of ≈ today”的快照，禁止伪装历史事实。
- 公司过滤：Employee.objects 已走 HorillaCompanyManager（当前选中学校），本 provider 不再手动过滤。
- 学历/职称/双师在 Legacy 阶段无权威事实，由 service/selector 返回 UNAVAILABLE，本 provider 不伪造。
- 严禁 except Exception: pass 后 fake zero；失败抛 HrProviderError 并携带追踪字段。
"""

from __future__ import annotations

from django.db.models import Count

from hr_control_center.context import HrRequestContext
from hr_control_center.providers.base import (
    DATA_BASIS_LEGACY_CURRENT_SNAPSHOT,
    LEGACY_ONLY,
    HrProviderError,
    ProviderResult,
    provider_ok,
)

# 年龄区间（总册 12.2 T03：固定区间，可配置）
AGE_GROUPS = (
    ("AGE_LE_30", "≤30", (None, 30)),
    ("AGE_31_35", "31-35", (31, 35)),
    ("AGE_36_40", "36-40", (36, 40)),
    ("AGE_41_45", "41-45", (41, 45)),
    ("AGE_46_50", "46-50", (46, 50)),
    ("AGE_51_55", "51-55", (51, 55)),
    ("AGE_GE_56", "56+", (56, None)),
)
AGE_GROUP_LABELS = {key: label for key, label, _ in AGE_GROUPS}

GENDER_LABELS = {
    "male": "男",
    "female": "女",
    "other": "其他",
}
GENDER_ORDER = ("male", "female", "other", "__none__")


class LegacyWorkforceProvider:
    """
    以 Horilla Employee / EmployeeWorkInformation 当前快照提供队伍结构数据。

    明确限制：
    - 只能回答“当前 as_of ≈ today”的结构类查询；
    - 学历/职称/双师等无权威事实的维度由上层返回 UNAVAILABLE，本类不伪造。
    """

    provider_key = "legacy_workforce"

    # ---- 公共查询 ---------------------------------------------------------

    def active_employee_qs(self):
        """当前学校 active 员工 queryset（HorillaCompanyManager 已按公司过滤）。"""
        from employee.models import Employee

        return Employee.objects.filter(is_active=True)

    def _base_kwargs(self, context):
        from django.utils import timezone

        return {
            "computed_at": timezone.now(),
            "source_updated_at": timezone.now(),
            "source": self.provider_key,
            "data_basis": DATA_BASIS_LEGACY_CURRENT_SNAPSHOT,
            "authority_mode": context.authority_mode or LEGACY_ONLY,
        }

    def _fail(self, context, metric_key, reason_code, exc):
        raise HrProviderError(
            self.provider_key,
            metric_key,
            reason_code,
            str(exc),
            tenant_id=context.tenant_id,
            scope_fingerprint=context.scope_fingerprint(),
        ) from exc

    # ---- 在岗人数 ---------------------------------------------------------

    def active_headcount(self, context) -> ProviderResult:
        metric_key = "workforce_headcount"
        try:
            count = self.active_employee_qs().count()
        except Exception as exc:
            self._fail(context, metric_key, "HEADCOUNT_QUERY_FAILED", exc)
        return provider_ok(
            {
                "value": count,
                "metricKey": metric_key,
                "scope": {
                    "type": context.scope.scope_type,
                    "id": context.scope.org_id,
                },
            },
            **self._base_kwargs(context),
        )

    # ---- 分组分布 ---------------------------------------------------------

    def _grouped_distribution(self, *, value_path, label_path):
        """通用 JOIN 分组：value_path 为分组主键路径，label_path 为其名称路径。"""
        qs = (
            self.active_employee_qs()
            .values(value_path, label_path)
            .annotate(count=Count("id"))
            .order_by("-count")
        )
        buckets = []
        for row in qs:
            value = row[value_path]
            label = row[label_path]
            key = str(value) if value is not None else "__none__"
            if not label:
                label = "未设置" if value is None else "未命名"
            buckets.append({"key": key, "label": label, "count": row["count"]})
        return {"buckets": buckets, "total": sum(b["count"] for b in buckets)}

    def distribution_by_employee_type(self, context) -> ProviderResult:
        metric_key = "workforce_distribution_personnel_category"
        try:
            data = self._grouped_distribution(
                value_path="employee_work_info__employee_type_id",
                label_path="employee_work_info__employee_type_id__employee_type",
            )
            data.update(
                {
                    "dimension": "personnel_category",
                    "interpretation": "RAW_EMPLOYEE_TYPE",
                }
            )
        except Exception as exc:
            self._fail(context, metric_key, "DISTRIBUTION_QUERY_FAILED", exc)
        return provider_ok(data, **self._base_kwargs(context))

    def distribution_by_department(self, context) -> ProviderResult:
        metric_key = "workforce_distribution_department"
        try:
            data = self._grouped_distribution(
                value_path="employee_work_info__department_id",
                label_path="employee_work_info__department_id__department",
            )
            data["dimension"] = "department"
        except Exception as exc:
            self._fail(context, metric_key, "DISTRIBUTION_QUERY_FAILED", exc)
        return provider_ok(data, **self._base_kwargs(context))

    def distribution_by_job_position(self, context) -> ProviderResult:
        metric_key = "workforce_distribution_job_position"
        try:
            data = self._grouped_distribution(
                value_path="employee_work_info__job_position_id",
                label_path="employee_work_info__job_position_id__job_position",
            )
            data["dimension"] = "job_position"
        except Exception as exc:
            self._fail(context, metric_key, "DISTRIBUTION_QUERY_FAILED", exc)
        return provider_ok(data, **self._base_kwargs(context))

    def distribution_by_gender(self, context) -> ProviderResult:
        metric_key = "workforce_distribution_gender"
        try:
            qs = (
                self.active_employee_qs()
                .values("gender")
                .annotate(count=Count("id"))
                .order_by("-count")
            )
            buckets = []
            for row in qs:
                gender = row["gender"]
                key = gender or "__none__"
                buckets.append(
                    {
                        "key": key,
                        "label": GENDER_LABELS.get(gender, gender or "未设置"),
                        "count": row["count"],
                    }
                )
            data = {
                "dimension": "gender",
                "buckets": buckets,
                "total": sum(b["count"] for b in buckets),
            }
        except Exception as exc:
            self._fail(context, metric_key, "DISTRIBUTION_QUERY_FAILED", exc)
        return provider_ok(data, **self._base_kwargs(context))

    def distribution_by_age_group(self, context) -> ProviderResult:
        metric_key = "workforce_distribution_age_group"
        if context.as_of is None:
            return ProviderResult.unavailable(
                provider_key=self.provider_key,
                metric_key=metric_key,
                reason_code="AS_OF_MISSING",
                message="年龄分组依赖 as_of 日期，当前请求缺少该参数。",
            )
        try:
            counts = {key: 0 for key, _, _ in AGE_GROUPS}
            unknown = 0
            for dob in self.active_employee_qs().values_list("dob", flat=True):
                age = self._age_on(dob, context.as_of)
                if age is None or age < 0:
                    unknown += 1
                    continue
                bucket = self._age_bucket(age)
                if bucket == "__unknown__":
                    unknown += 1
                else:
                    counts[bucket] += 1
            buckets = [
                {"key": key, "label": AGE_GROUP_LABELS[key], "count": counts[key]}
                for key in counts
                if counts[key] > 0
            ]
            if unknown > 0:
                buckets.append(
                    {"key": "__unknown__", "label": "未设置/日期异常", "count": unknown}
                )
            data = {
                "dimension": "age_group",
                "buckets": buckets,
                "total": sum(b["count"] for b in buckets),
            }
        except Exception as exc:
            self._fail(context, metric_key, "DISTRIBUTION_QUERY_FAILED", exc)
        return provider_ok(data, **self._base_kwargs(context))

    @staticmethod
    def _age_on(dob, as_of):
        """按 as_of（学校时区）计算周岁；dob 缺失返回 None。"""
        if not dob:
            return None
        return as_of.year - dob.year - (
            1 if (as_of.month, as_of.day) < (dob.month, dob.day) else 0
        )

    @staticmethod
    def _age_bucket(age):
        for key, _, (low, high) in AGE_GROUPS:
            if (low is None or age >= low) and (high is None or age <= high):
                return key
        return "__unknown__"

    # ---- 组织对比 ---------------------------------------------------------

    def org_comparison(self, context) -> ProviderResult:
        """
        学院/部门对比宽表：按部门输出在岗人数与真实可确认的结构分布。

        Legacy 阶段“组织”以 Horilla Department 为准（HR02/HR03 学院模型未建设）。
        """
        metric_key = "workforce_org_comparison"
        if context.as_of is None:
            return ProviderResult.unavailable(
                provider_key=self.provider_key,
                metric_key=metric_key,
                reason_code="AS_OF_MISSING",
                message="组织对比包含年龄分组，依赖 as_of 日期，当前请求缺少该参数。",
            )
        try:
            qs = self.active_employee_qs()

            def _dept_key(dept_id):
                return str(dept_id) if dept_id is not None else "__none__"

            rows = {}
            order = []

            # 1. 各部门在岗人数
            for row in qs.values(
                "employee_work_info__department_id",
                "employee_work_info__department_id__department",
            ).annotate(count=Count("id")):
                key = _dept_key(row["employee_work_info__department_id"])
                entry = rows.setdefault(
                    key,
                    {
                        "departmentId": row["employee_work_info__department_id"],
                        "department": row["employee_work_info__department_id__department"]
                        or "未设置",
                        "headcount": 0,
                        "gender": {},
                        "employeeType": {},
                        "ageGroup": {},
                    },
                )
                entry["headcount"] += row["count"]
                if key not in order:
                    order.append(key)

            # 2. 各部门性别分布
            for row in qs.values(
                "employee_work_info__department_id", "gender"
            ).annotate(count=Count("id")):
                entry = rows[_dept_key(row["employee_work_info__department_id"])]
                gkey = row["gender"] or "__none__"
                entry["gender"][gkey] = entry["gender"].get(gkey, 0) + row["count"]

            # 3. 各部门 employee_type 分布
            for row in qs.values(
                "employee_work_info__department_id",
                "employee_work_info__employee_type_id",
                "employee_work_info__employee_type_id__employee_type",
            ).annotate(count=Count("id")):
                entry = rows[_dept_key(row["employee_work_info__department_id"])]
                tkey = (
                    str(row["employee_work_info__employee_type_id"])
                    if row["employee_work_info__employee_type_id"] is not None
                    else "__none__"
                )
                label = (
                    row["employee_work_info__employee_type_id__employee_type"]
                    or ("未设置" if tkey == "__none__" else "未命名")
                )
                cur = entry["employeeType"].get(tkey)
                if cur is None:
                    entry["employeeType"][tkey] = {
                        "key": tkey,
                        "label": label,
                        "count": row["count"],
                    }
                else:
                    cur["count"] += row["count"]

            # 4. 各部门年龄分组（Python 侧按 as_of 计算周岁，避免 SQL 近似年龄）
            for dept_id, dob in qs.values_list(
                "employee_work_info__department_id", "dob"
            ):
                entry = rows[_dept_key(dept_id)]
                age = self._age_on(dob, context.as_of)
                if age is None or age < 0:
                    bucket = "__unknown__"
                    label = "未设置/日期异常"
                else:
                    bucket = self._age_bucket(age)
                    label = AGE_GROUP_LABELS.get(bucket, "未设置/日期异常")
                cur = entry["ageGroup"].get(bucket)
                if cur is None:
                    entry["ageGroup"][bucket] = {
                        "key": bucket,
                        "label": label,
                        "count": 1,
                    }
                else:
                    cur["count"] += 1

            out_rows = []
            for key in order:
                entry = rows[key]
                out_rows.append(
                    {
                        "departmentId": entry["departmentId"],
                        "department": entry["department"],
                        "headcount": entry["headcount"],
                        "gender": sorted(
                            (
                                {
                                    "key": gkey,
                                    "label": GENDER_LABELS.get(gkey, gkey or "未设置"),
                                    "count": count,
                                }
                                for gkey, count in entry["gender"].items()
                            ),
                            key=lambda b: (
                                GENDER_ORDER.index(b["key"])
                                if b["key"] in GENDER_ORDER
                                else len(GENDER_ORDER)
                            ),
                        ),
                        "employeeType": sorted(
                            entry["employeeType"].values(),
                            key=lambda b: b["count"],
                            reverse=True,
                        ),
                        "ageGroup": sorted(
                            entry["ageGroup"].values(),
                            key=lambda b: b["count"],
                            reverse=True,
                        ),
                    }
                )
            data = {
                "rows": out_rows,
                "total": sum(e["headcount"] for e in rows.values()),
            }
        except Exception as exc:
            self._fail(context, metric_key, "ORG_COMPARISON_QUERY_FAILED", exc)
        return provider_ok(data, **self._base_kwargs(context))

    def distribution_by_hr02_org(self, context: HrRequestContext) -> ProviderResult:
        """
        HR02-aware 学院分布（总册 1.3：HR02 权威化后切 HR02 组织事实）。

        仅当 authority_mode 为 HR02_AUTHORITY（或 DUAL_READ_COMPARE 显式对账）
        才返回 HR02 组织数据（dataBasis = HR02_AUTHORITY）；
        LEGACY_ONLY 阶段 → UNAVAILABLE（不静默切源、不 fallback legacy）。
        """
        from hr_control_center.providers.base import (
            AUTHORITY_ONLY,
            DATA_BASIS_AUTHORITATIVE_EFFECTIVE_FACT,
            ProviderResult,
        )

        metric_key = "workforce_distribution_org"
        mode = getattr(context, "authority_mode", None)
        # HR01 context 用 LEGACY_ONLY/DUAL_READ_COMPARE/AUTHORITY_ONLY。
        # HR02 权威化由 cutover 决定；这里仅在 DUAL_READ_COMPARE（显式对账）时切 HR02。
        # LEGACY_ONLY → UNAVAILABLE（不静默切源、不 fallback legacy）。
        if mode in ("LEGACY_ONLY", "LEGACY_STRUCTURE_ONLY", None):
            return ProviderResult.unavailable(
                provider_key=self.provider_key,
                metric_key=metric_key,
                reason_code="HR02_NOT_AUTHORITY",
                message="HR02 组织事实尚未进入权威/对账模式，学院分布暂用当前快照。",
                authority_mode=context.authority_mode,
            )
        try:
            from hr_structure.models import HrLegacyObjectLink, HrOrganizationVersion
            from hr_structure.scope import Hr02Scope
            from hr_structure.selectors.effective import children_as_of

            scope = Hr02Scope("SCHOOL", tenant_id=context.tenant_id)
            as_of = context.as_of or context.today()
            root = (
                HrOrganizationVersion.objects.filter(
                    tenant_id=context.tenant_id,
                    status__in=("APPROVED", "EFFECTIVE", "SUPERSEDED"),
                    org_type="SCHOOL",
                )
                .filter(validity_to__isnull=True)
                .first()
            )
            if root is None:
                return ProviderResult.unavailable(
                    provider_key=self.provider_key,
                    metric_key=metric_key,
                    reason_code="HR02_ROOT_MISSING",
                    message="学校根组织尚未建立",
                    authority_mode=context.authority_mode,
                )

            # 一级组织（学院/部门）列表
            colleges = list(children_as_of(context.tenant_id, root.organization_id_id, as_of, dimension="ADMIN"))
            buckets = []
            total = 0
            for version in colleges:
                org_id = version.organization_id_id
                # 该组织下人员数：从 EmployeeWorkInformation.department 无法直接映射 HR02 org，
                # 需通过 HrLegacyObjectLink 找 legacy Department，再查人数（若映射存在）。
                link = (
                    HrLegacyObjectLink.objects.filter(
                        tenant_id=context.tenant_id,
                        domain_entity_type="organization",
                        domain_entity_id=str(org_id),
                        legacy_model="department",
                    ).first()
                )
                count = 0
                if link:
                    from employee.models import EmployeeWorkInformation

                    count = EmployeeWorkInformation.objects.filter(
                        employee_id__is_active=True,
                        department_id_id=int(link.legacy_pk),
                    ).count()
                buckets.append(
                    {"key": org_id, "label": version.name, "count": count}
                )
                total += count

            data = {
                "dimension": "department",
                "buckets": sorted(buckets, key=lambda b: b["count"], reverse=True),
                "total": total,
                "interpretation": "HR02_AUTHORITY_ORG",
            }
        except Exception as exc:
            self._fail(context, metric_key, "HR02_ORG_DISTRIBUTION_FAILED", exc)
        kwargs = self._base_kwargs(context)
        kwargs["data_basis"] = DATA_BASIS_AUTHORITATIVE_EFFECTIVE_FACT
        return provider_ok(data, **kwargs)
