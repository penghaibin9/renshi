"""
hr_control_center/providers/legacy_employee.py

LegacyEmployeeMetricProvider —— HR02/HR03 就绪前的 current-snapshot 指标源。

硬合同（总册 1.1 / 30 节）：
- dataBasis = LEGACY_CURRENT_SNAPSHOT，不得伪装“历史事实”。
- 旧系统快照无法回答的正式指标 → UNAVAILABLE，不显示 0；HR01 会路由到对应权威域。
- 公司过滤：Employee.objects 已走 HorillaCompanyManager（当前选中学校）。
- 严禁 except Exception: pass 后 fake zero。
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from django.apps import apps
from django.db.models import Q

from hr_control_center.context import HrRequestContext
from hr_control_center.providers.base import (
    DATA_BASIS_LEGACY_CURRENT_SNAPSHOT,
    LEGACY_ONLY,
    HrProviderError,
    ProviderResult,
    provider_ok,
)
from hr_control_center.services.metric_registry import (
    UNAVAILABLE,
    get_registry,
)


def _module_available(app_label: str) -> bool:
    return apps.is_installed(app_label)


def _emp_model():
    from employee.models import Employee

    return Employee


def _work_info_model():
    from employee.models import EmployeeWorkInformation

    return EmployeeWorkInformation


def _active_employee_ids_qs():
    """当前学校 active 员工 queryset（走 HorillaCompanyManager 公司过滤）。"""
    return _emp_model().objects.filter(is_active=True)


class LegacyEmployeeMetricProvider:
    """
    以 Horilla Employee/EmployeeWorkInformation 当前快照提供指标。

    明确限制：
    - 只能回答“当前 as_of ≈ today”的人数类指标；
    - 历史 headcount/结构 → 由调用方返回 UNAVAILABLE（本文不伪造趋势）。
    """

    provider_key = "legacy_employee"
    supported_metric_keys = {
        "active_headcount",
        "full_time_teacher",
        "double_teacher_valid",
        "new_join_ytd",
        "departure_ytd",
    }

    def get_metric(self, metric_key: str, context: HrRequestContext) -> ProviderResult:
        if metric_key not in self.supported_metric_keys:
            return ProviderResult.unavailable(
                provider_key=self.provider_key,
                metric_key=metric_key,
                reason_code="METRIC_NOT_SUPPORTED",
            )

        definition = get_registry().get(metric_key)

        if metric_key == "active_headcount":
            return self._active_headcount(context, definition)
        if metric_key == "full_time_teacher":
            return self._full_time_teacher(context, definition)
        if metric_key == "double_teacher_valid":
            return self._double_teacher(context, definition)
        if metric_key == "new_join_ytd":
            return self._new_join_ytd(context, definition)
        if metric_key == "departure_ytd":
            return self._departure_ytd(context, definition)
        return ProviderResult.unavailable(
            provider_key=self.provider_key,
            metric_key=metric_key,
            reason_code="METRIC_NOT_SUPPORTED",
        )

    # ---- 指标实现 ---------------------------------------------------------

    def _base_kwargs(self, definition, context):
        from django.utils import timezone

        return {
            "computed_at": timezone.now(),
            "source_updated_at": timezone.now(),
            "source": self.provider_key,
            "data_basis": DATA_BASIS_LEGACY_CURRENT_SNAPSHOT,
            "definition_version": definition.definition_version,
            "authority_mode": context.authority_mode or LEGACY_ONLY,
        }

    def _active_headcount(self, context, definition):
        try:
            count = _active_employee_ids_qs().count()
            return provider_ok(
                {
                    "value": count,
                    "metricKey": definition.key,
                    "definitionVersion": definition.definition_version,
                    "dataBasis": DATA_BASIS_LEGACY_CURRENT_SNAPSHOT,
                    "scope": {
                        "type": context.scope.scope_type,
                        "id": context.scope.org_id,
                    },
                },
                **self._base_kwargs(definition, context),
            )
        except Exception as exc:
            raise HrProviderError(
                self.provider_key,
                definition.key,
                "HEADCOUNT_QUERY_FAILED",
                str(exc),
                tenant_id=context.tenant_id,
                scope_fingerprint=context.scope_fingerprint(),
            ) from exc

    def _full_time_teacher(self, context, definition):
        """
        高校“专任教师”口径在 Legacy 阶段无法可靠判定：
        Horilla EmployeeType 是自由文本字典，没有 FULL_TIME_TEACHER 配置。

        在没有 HR03 人员类别字典前，本指标返回 UNAVAILABLE，
        不得把“非空 employee_type”伪装成专任教师数。
        """
        return ProviderResult.unavailable(
            provider_key=self.provider_key,
            metric_key=definition.key,
            reason_code="PERSONNEL_CATEGORY_DICT_MISSING",
            message="专任教师口径依赖 HR03 人员类别正式字典，当前系统快照无法可靠判定。",
            definition_version=definition.definition_version,
            authority_mode=context.authority_mode or LEGACY_ONLY,
        )

    def _double_teacher(self, context, definition):
        if not _module_available("hr09"):
            return ProviderResult.unavailable(
                provider_key=self.provider_key,
                metric_key=definition.key,
                reason_code="MODULE_NOT_AVAILABLE",
                message="该指标将在「双师型教师」模块启用后提供。",
                definition_version=definition.definition_version,
                authority_mode=context.authority_mode or LEGACY_ONLY,
            )
        # 旧 Employee 快照不拥有 HR09 正式认定事实；由 HR01 权威路由处理。
        return ProviderResult.unavailable(
            provider_key=self.provider_key,
            metric_key=definition.key,
            reason_code="MODULE_NOT_AVAILABLE",
            message="旧人员快照不包含双师认定事实，请使用 HR09 正式数据源。",
            definition_version=definition.definition_version,
            authority_mode=context.authority_mode or LEGACY_ONLY,
        )

    def _new_join_ytd(self, context, definition):
        """
        本年新进 = 当年 date_joining 在 [1/1, as_of] 的员工数。
        仅限 current snapshot 口径：无法区分“首次入校”与“当前关系开始日”。
        """
        if context.as_of is None:
            return self._fail(definition, context, "AS_OF_MISSING")
        try:
            from_date = date(context.as_of.year, 1, 1)
            count = (
                _work_info_model()
                .objects.filter(
                    employee_id__is_active=True,
                    date_joining__gte=from_date,
                    date_joining__lte=context.as_of,
                )
                .count()
            )
            return provider_ok(
                {
                    "value": count,
                    "metricKey": definition.key,
                    "definitionVersion": definition.definition_version,
                    "dataBasis": DATA_BASIS_LEGACY_CURRENT_SNAPSHOT,
                    "period": {
                        "from": from_date.isoformat(),
                        "to": context.as_of.isoformat(),
                    },
                },
                **self._base_kwargs(definition, context),
            )
        except Exception as exc:
            raise HrProviderError(
                self.provider_key,
                definition.key,
                "NEW_JOIN_QUERY_FAILED",
                str(exc),
                tenant_id=context.tenant_id,
                scope_fingerprint=context.scope_fingerprint(),
            ) from exc

    def _departure_ytd(self, context, definition):
        """
        本年离退：Legacy 快照无法区分离职/调出/退休（is_active=False 无离退日期）。
        真实口径依赖 HR03 权威事实 → UNAVAILABLE，禁止用 contract_end_date 猜测。
        """
        return ProviderResult.unavailable(
            provider_key=self.provider_key,
            metric_key=definition.key,
            reason_code="NO_EXIT_FACT_IN_LEGACY",
            message="本年离退需要 HR03/HR16 正式离退记录，当前系统快照无法可靠计算。",
            definition_version=definition.definition_version,
            authority_mode=context.authority_mode or LEGACY_ONLY,
        )

    def _fail(self, definition, context, reason):
        raise HrProviderError(
            self.provider_key,
            definition.key,
            reason,
            tenant_id=context.tenant_id,
            scope_fingerprint=context.scope_fingerprint(),
        )
