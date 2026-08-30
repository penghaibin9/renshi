"""
hr_changes.models —— HR06 权威模型包（S1 骨架 → S8 扩展）。

分层（总册 §5.3 NEW + §54 目录）：
- S1: action.py / reason.py / field_definition.py
- S2: case.py / proposal.py / transition.py / impact.py / snapshot.py /
       downstream.py / temporary.py / correction.py / rescind.py / bulk.py
- S6: temporary.py（+HrTemporaryAssignmentExtension）
- S8: outbox.py
"""

from hr_changes.models.action import HrChangeAction
from hr_changes.models.authority import HrChangeAuthorityMode
from hr_changes.models.bulk import HrBulkChangeBatch, HrBulkChangeItem
from hr_changes.models.case import HrPersonnelChangeCase
from hr_changes.models.correction import HrChangeCorrection
from hr_changes.models.downstream import HrChangeDownstreamEffect
from hr_changes.models.field_definition import HrChangeFieldDefinition
from hr_changes.models.impact import HrChangeImpactSnapshot
from hr_changes.models.outbox import HrChangeOutboxEvent
from hr_changes.models.permission import HrChangePermissionMeta
from hr_changes.models.proposal import HrChangeProposal
from hr_changes.models.reason import HrChangeReason
from hr_changes.models.rescind import HrChangeRescind
from hr_changes.models.snapshot import (
    HrChangeApprovalSnapshot,
    HrChangeAuthorityReceipt,
    HrChangeEffectiveSnapshot,
)
from hr_changes.models.temporary import (
    HrTemporaryAssignmentExtension,
    HrTemporaryAssignmentLink,
)
from hr_changes.models.transition import HrChangeTransition

__all__ = [
    "HrChangeAction",
    "HrChangeAuthorityMode",
    "HrChangeReason",
    "HrChangeFieldDefinition",
    "HrPersonnelChangeCase",
    "HrChangeProposal",
    "HrChangeTransition",
    "HrChangeImpactSnapshot",
    "HrChangeApprovalSnapshot",
    "HrChangeEffectiveSnapshot",
    "HrChangeAuthorityReceipt",
    "HrChangeDownstreamEffect",
    "HrTemporaryAssignmentLink",
    "HrTemporaryAssignmentExtension",
    "HrChangeCorrection",
    "HrChangeRescind",
    "HrBulkChangeBatch",
    "HrBulkChangeItem",
    "HrChangeOutboxEvent",
    "HrChangePermissionMeta",
]
