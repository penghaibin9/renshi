"""
hr_time/models/__init__.py

HR11 模型包。业务模型按总册 §185 顺序分模块：
- base.py       抽象基类（tenant_id NOT NULL 等 A0 DB 层约束）
- permissions.py 权限元数据
- policy.py     S2 工作制度与规则版本（HrTimePolicyPack/Version/RecordingProfile）
- calendar.py   S3 工作日历与版本（HrWorkCalendar/Version/Day）
- schedule.py   S3 班次/轮班/排班（HrShiftDefinition/Version/WorkPattern/ScheduleAssignment/Exception）
- event.py      S4 原始打卡事件账本（HrRawTimeEvent/Source/Device）
"""

from hr_time.models.base import TimeTenantModel
from hr_time.models.permissions import HrTimePermissionMeta
from hr_time.models.policy import (
    HrTimePolicyPack,
    HrTimePolicyVersion,
    HrTimeRecordingProfile,
)
from hr_time.models.calendar import HrCalendarDay, HrWorkCalendar, HrWorkCalendarVersion
from hr_time.models.schedule import (
    HrScheduleAssignment,
    HrScheduleException,
    HrShiftDefinition,
    HrShiftVersion,
    HrWorkPattern,
)
from hr_time.models.event import (
    HrAttendanceDevice,
    HrRawTimeEvent,
    HrTimeEventPair,
    HrTimeEventSource,
)

__all__ = [
    "TimeTenantModel",
    "HrTimePermissionMeta",
    "HrTimePolicyPack",
    "HrTimePolicyVersion",
    "HrTimeRecordingProfile",
    "HrWorkCalendar",
    "HrWorkCalendarVersion",
    "HrCalendarDay",
    "HrShiftDefinition",
    "HrShiftVersion",
    "HrWorkPattern",
    "HrScheduleAssignment",
    "HrScheduleException",
    "HrTimeEventSource",
    "HrAttendanceDevice",
    "HrRawTimeEvent",
    "HrTimeEventPair",
]
