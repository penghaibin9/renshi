"""
hr_control_center/selectors/overview.py

Overview selector —— 只读；接受已解析的 HrRequestContext；返回 domain DTO；不 render HTML。
"""

from __future__ import annotations

from hr_control_center.context import HrRequestContext


class OverviewSelector:
    """人事总览数据查询（当前阶段直接由 OverviewService + provider 提供，本类为后续分页/钻取预留）。"""

    def __init__(self, context: HrRequestContext):
        self.context = context

    def list_recent_changes(self, limit: int = 12):
        """
        最近人事变化（入职/调动/职称/聘任/离退时间线）。

        Legacy 快照阶段：只有“当前信息”，无历史异动事实 → 返回空并标记来源。
        不伪造异动时间线。
        """
        return {
            "items": [],
            "dataBasis": "LEGACY_CURRENT_SNAPSHOT",
            "available": False,
            "message": "最近异动时间线依赖 HR03 权威任职历史，Legacy 快照无法提供。",
        }
