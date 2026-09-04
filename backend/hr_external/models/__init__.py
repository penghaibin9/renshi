"""
hr_external.models —— HR08 权威模型包（S1 骨架 → S2 Authority Models）。

分层（总册 §80 / §141）：
- S1: category.py
- S2: profile.py / engagement.py / assignment.py / hiring.py / ethics.py / conflict.py /
      access.py / lifecycle.py / audit.py
- S3: qualification.py / talent.py
- S4: contribution.py / workspace.py
- S7: task.py / workload.py
- S8: renewal.py / exit.py
"""

from hr_external.models.access import (
    HrExternalAccessGrant,
    HrExternalProvisioningRequest,
)
from hr_external.models.academic import (
    HrExternalAcademicIdentity,
    HrExternalAcademicProvisioningRequest,
)
from hr_external.models.assignment import HrExternalEngagementAssignment
from hr_external.models.audit import HrExternalAuditEvent, HrSensitiveExternalAccessLog
from hr_external.models.authority import HrExternalAuthorityConfig
from hr_external.models.category import HrExternalCategory
from hr_external.models.conflict import HrExternalConflictDeclaration
from hr_external.models.engagement import HrExternalEngagement
from hr_external.models.ethics import HrExternalEthicsReview
from hr_external.models.hiring import HrExternalHiringCase
from hr_external.models.import_models import HrExternalImportJob, HrExternalImportRow
from hr_external.models.industry import (
    HrExternalContribution,
    HrExternalIndustryProfile,
    HrExternalWorkspace,
)
from hr_external.models.lifecycle import HrExternalLifecycleEvent
from hr_external.models.material import HrExternalFileTicket, HrExternalMaterial
from hr_external.models.profile import HrExternalTeacherProfile
from hr_external.models.portal import HrExternalPortalToken
from hr_external.models.permissions import HrExternalPermissionMeta
from hr_external.models.projection import HrExternalProjectionState
from hr_external.models.renewal_exit import HrExternalExitCase, HrExternalRenewalReview
from hr_external.models.task import (
    HrExternalSettlementBasis,
    HrExternalServiceTask,
    HrExternalTaskEvidence,
    HrExternalTaskPlan,
    HrExternalWorkloadRecord,
)

__all__ = [
    "HrExternalCategory",
    "HrExternalTeacherProfile",
    "HrExternalEngagement",
    "HrExternalEngagementAssignment",
    "HrExternalHiringCase",
    "HrExternalEthicsReview",
    "HrExternalConflictDeclaration",
    "HrExternalAccessGrant",
    "HrExternalProvisioningRequest",
    "HrExternalAcademicIdentity",
    "HrExternalAcademicProvisioningRequest",
    "HrExternalLifecycleEvent",
    "HrExternalAuditEvent",
    "HrSensitiveExternalAccessLog",
    "HrExternalImportJob",
    "HrExternalImportRow",
    "HrExternalIndustryProfile",
    "HrExternalContribution",
    "HrExternalWorkspace",
    "HrExternalTaskPlan",
    "HrExternalServiceTask",
    "HrExternalTaskEvidence",
    "HrExternalWorkloadRecord",
    "HrExternalSettlementBasis",
    "HrExternalRenewalReview",
    "HrExternalExitCase",
    "HrExternalProjectionState",
    "HrExternalAuthorityConfig",
    "HrExternalMaterial",
    "HrExternalFileTicket",
    "HrExternalPortalToken",
    "HrExternalPermissionMeta",
]
