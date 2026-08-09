"""
hr_staff.models —— HR03 权威模型包（S1 骨架 → 逐步填充）。

分层（总册 §7 六层真相）：
- S2: person.py / identity.py / staff.py / mapping.py / audit.py / sensitive.py（本阶段）
- S3: employment.py / assignment.py / status_history.py
- S7: education.py / credential.py
- S8: material.py
- S9: correction.py
- S10: events.py
"""

from hr_staff.models.assignment import HrStaffAssignment
from hr_staff.models.audit import HrStaffAuditEvent, HrSensitiveAccessLog
from hr_staff.models.credential import HrCredential, HrTalentHonor
from hr_staff.models.correction import (
    HrCorrectionCase,
    HrCorrectionItem,
    HrFieldGovernancePolicy,
)
from hr_staff.models.education import HrDegreeRecord, HrEducationExperience, HrWorkExperience
from hr_staff.models.events import HrBusinessEventInbox, HrOutboxEvent
from hr_staff.models.export_models import HrExportJob
from hr_staff.models.employment import HrEmploymentRelationship
from hr_staff.models.import_models import HrImportIssue, HrImportJob, HrImportRow
from hr_staff.models.identity import HrPersonIdentityDocument
from hr_staff.models.mapping import (
    HrAccountLink,
    HrExternalIdentityMapping,
    HrLegacyProjectionState,
)
from hr_staff.models.material import (
    HrMaterialDownloadTicket,
    HrMaterialRequest,
    HrStaffMaterial,
    HrStaffMaterialVersion,
)
from hr_staff.models.number_sequence import HrStaffNumberSequence
from hr_staff.models.person import HrEmergencyContact, HrPerson, HrPersonContact
from hr_staff.models.permission_meta import HrStaffPermissionMeta
from hr_staff.models.staff import HrStaffMaster
from hr_staff.models.status_history import HrStatusHistory

__all__ = [
    "HrPerson",
    "HrPersonContact",
    "HrEmergencyContact",
    "HrPersonIdentityDocument",
    "HrStaffMaster",
    "HrEmploymentRelationship",
    "HrStaffAssignment",
    "HrStatusHistory",
    "HrEducationExperience",
    "HrDegreeRecord",
    "HrWorkExperience",
    "HrCredential",
    "HrTalentHonor",
    "HrStaffMaterial",
    "HrStaffMaterialVersion",
    "HrMaterialRequest",
    "HrMaterialDownloadTicket",
    "HrStaffNumberSequence",
    "HrCorrectionCase",
    "HrCorrectionItem",
    "HrFieldGovernancePolicy",
    "HrOutboxEvent",
    "HrBusinessEventInbox",
    "HrExportJob",
    "HrImportJob",
    "HrImportRow",
    "HrImportIssue",
    "HrAccountLink",
    "HrExternalIdentityMapping",
    "HrLegacyProjectionState",
    "HrStaffAuditEvent",
    "HrSensitiveAccessLog",
    "HrStaffPermissionMeta",
]
