"""
hr_changes.models —— HR06 权威模型包（S1 骨架 → S2 扩展）。

分层（总册 §5.3 NEW + §54 目录）：
- S1: action.py / reason.py / field_definition.py
- S2: case.py / proposal.py / transition.py / impact.py / snapshot.py /
       downstream.py / temporary.py / correction.py / rescind.py / bulk.py
"""

from hr_changes.models.action import HrChangeAction
from hr_changes.models.field_definition import HrChangeFieldDefinition
from hr_changes.models.reason import HrChangeReason

__all__ = [
    "HrChangeAction",
    "HrChangeReason",
    "HrChangeFieldDefinition",
]
