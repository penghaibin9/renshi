"""
hr_changes.services —— HR06 服务包。
"""

from hr_changes.services.approval_service import (
    ApprovalService,
    ApprovalServiceError,
)
from hr_changes.services.case_number_service import CaseNumberService
from hr_changes.services.change_service import ChangeService, ChangeServiceError
from hr_changes.services.identity_change_service import IdentityChangeService
from hr_changes.services.impact_service import ImpactService
from hr_changes.services.state_machine import (
    ChangeStateError,
    allowed_next_status,
    can_transition,
    transition,
)
from hr_changes.services.transfer_service import TransferService
from hr_changes.services.validation_service import ValidationService

__all__ = [
    "ApprovalService",
    "ApprovalServiceError",
    "CaseNumberService",
    "ChangeService",
    "ChangeServiceError",
    "IdentityChangeService",
    "ImpactService",
    "ChangeStateError",
    "allowed_next_status",
    "can_transition",
    "transition",
    "TransferService",
    "ValidationService",
]
