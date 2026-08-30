"""
hr_onboarding.models —— HR05 权威模型包（总册 §6-§25）。

分层：
- template.py    HrOnboardingTemplate(+Version)/StageDefinition/TaskDefinition
- case.py        HrOnboardingCase/StageTransition/ReportDelay/ReportCheckin
- prehire.py     HrPrehireProfile/HrPrehirePortalAccess/HrOnboardingDataConflict
- material.py    Requirement/Material/Verification/PersonnelFileTransfer
- activation.py  HrActivationAttempt/HrOnboardingActivationSnapshot/Amendment
- task.py        HrOnboardingTaskInstance
- provisioning.py HrProvisioningRequest
- probation.py   HrProbationCase/Goal/Extension/Review
- audit.py       HrOnboardingAuditEvent

硬合同：
- 所有权威表显式 tenant_id（00 §8 A0 fail-closed DB 层）；
- 跨域 FK 直指 hr_structure（HR02 稳定 ID）与 hr_staff（HR03）；
- hr03_*_id 以 UUID 引用，不建立跨 app FK 耦合。
"""

from hr_onboarding.models.activation import (
    HrActivationAttempt,
    HrOnboardingActivationAmendment,
    HrOnboardingActivationSnapshot,
)
from hr_onboarding.models.audit import HrOnboardingAuditEvent
from hr_onboarding.models.authority import HrOnboardingAuthorityMode
from hr_onboarding.models.case import (
    HrOnboardingCase,
    HrOnboardingStageTransition,
    HrReportCheckin,
    HrReportDelay,
)
from hr_onboarding.models.material import (
    HrMaterialVerification,
    HrOnboardingMaterial,
    HrOnboardingMaterialRequirement,
    HrPersonnelFileTransfer,
)
from hr_onboarding.models.outbox import HrOnboardingOutboxEvent
from hr_onboarding.models.prehire import (
    HrOnboardingDataConflict,
    HrPrehirePortalAccess,
    HrPrehireProfile,
)
from hr_onboarding.models.probation import (
    HrProbationCase,
    HrProbationExtension,
    HrProbationGoal,
    HrProbationReview,
)
from hr_onboarding.models.provisioning import HrProvisioningRequest
from hr_onboarding.models.task import HrOnboardingTaskInstance
from hr_onboarding.models.template import (
    HrOnboardingStageDefinition,
    HrOnboardingTaskDefinition,
    HrOnboardingTemplate,
    HrOnboardingTemplateVersion,
)

__all__ = [
    "HrOnboardingTemplate",
    "HrOnboardingTemplateVersion",
    "HrOnboardingStageDefinition",
    "HrOnboardingTaskDefinition",
    "HrOnboardingCase",
    "HrOnboardingStageTransition",
    "HrReportDelay",
    "HrReportCheckin",
    "HrPrehireProfile",
    "HrPrehirePortalAccess",
    "HrOnboardingDataConflict",
    "HrOnboardingMaterialRequirement",
    "HrOnboardingMaterial",
    "HrMaterialVerification",
    "HrPersonnelFileTransfer",
    "HrActivationAttempt",
    "HrOnboardingActivationAmendment",
    "HrOnboardingActivationSnapshot",
    "HrOnboardingTaskInstance",
    "HrProvisioningRequest",
    "HrProbationCase",
    "HrProbationGoal",
    "HrProbationExtension",
    "HrProbationReview",
    "HrOnboardingOutboxEvent",
    "HrOnboardingAuthorityMode",
    "HrOnboardingAuditEvent",
]
