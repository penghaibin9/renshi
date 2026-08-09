"""
hr_changes.services —— HR06 服务包。
"""

from hr_changes.services.case_number_service import CaseNumberService
from hr_changes.services.state_machine import (
    ChangeStateError,
    allowed_next_status,
    can_transition,
    transition,
)

__all__ = [
    "CaseNumberService",
    "ChangeStateError",
    "allowed_next_status",
    "can_transition",
    "transition",
]
