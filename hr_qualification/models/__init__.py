"""
hr_qualification/models/__init__.py —— HR09 全部权威模型（S2-S6 施工完成）。

按总册 §17 权威领域模型结构：
S2 ── Credential Authority
S4 ── Rule Pack Structure
S5 ── Batch + Application + Evidence
S6 ── Review + Recognition + Recheck + EvidenceUsage
"""

# ---- S2: Credential（8 models）----
from hr_qualification.models.credential_catalog import HrCredentialCatalogItem
from hr_qualification.models.credential import HrPersonCredential
from hr_qualification.models.document import HrCredentialDocument
from hr_qualification.models.renewal import HrCredentialRenewal
from hr_qualification.models.requirement import HrCredentialRequirement
from hr_qualification.models.risk import HrQualificationRiskCase
from hr_qualification.models.status_event import HrCredentialStatusEvent
from hr_qualification.models.verification import HrCredentialVerification

# ---- S4: Rule Pack（4 models）----
from hr_qualification.models.evidence_requirement import HrDoubleTeacherEvidenceRequirement
from hr_qualification.models.exception_route import HrDoubleTeacherExceptionRoute
from hr_qualification.models.rule import HrDoubleTeacherRule
from hr_qualification.models.rule_pack import (
    HrDoubleTeacherRulePack,
    HrDoubleTeacherRulePackVersion,
    RulePackStatus,
)

# ---- S5: Batch + Application + Evidence（3 models）----
from hr_qualification.models.batch import HrDoubleTeacherRecognitionBatch
from hr_qualification.models.application import HrDoubleTeacherApplication
from hr_qualification.models.evidence import (
    HrDoubleTeacherEvidenceItem,
    HrDoubleTeacherEvidencePackage,
)

# ---- S6: Review + Recognition + Recheck + Usage + Objection（9 models）----
from hr_qualification.models.review import (
    HrDoubleTeacherFinalDecision,
    HrDoubleTeacherFinalDecisionAmendment,
    HrDoubleTeacherPanelDecision,
    HrDoubleTeacherPanelMember,
    HrDoubleTeacherReviewPanel,
    HrDoubleTeacherScoreSheet,
    HrDoubleTeacherVote,
)
from hr_qualification.models.recognition import HrDoubleTeacherRecognition
from hr_qualification.models.recheck import HrDoubleTeacherRecheckCase
from hr_qualification.models.evidence_usage import HrEvidenceUsage
from hr_qualification.models.objection import HrDoubleTeacherObjection

__all__ = [
    # S2
    "HrCredentialCatalogItem",
    "HrCredentialDocument",
    "HrCredentialRenewal",
    "HrCredentialRequirement",
    "HrCredentialStatusEvent",
    "HrCredentialVerification",
    "HrPersonCredential",
    "HrQualificationRiskCase",
    # S4
    "HrDoubleTeacherEvidenceRequirement",
    "HrDoubleTeacherExceptionRoute",
    "HrDoubleTeacherRule",
    "HrDoubleTeacherRulePack",
    "HrDoubleTeacherRulePackVersion",
    "RulePackStatus",
    # S5
    "HrDoubleTeacherApplication",
    "HrDoubleTeacherEvidenceItem",
    "HrDoubleTeacherEvidencePackage",
    "HrDoubleTeacherRecognitionBatch",
    # S6
    "HrDoubleTeacherFinalDecision",
    "HrDoubleTeacherFinalDecisionAmendment",
    "HrDoubleTeacherObjection",
    "HrDoubleTeacherPanelDecision",
    "HrDoubleTeacherPanelMember",
    "HrDoubleTeacherRecheckCase",
    "HrDoubleTeacherRecognition",
    "HrDoubleTeacherReviewPanel",
    "HrDoubleTeacherScoreSheet",
    "HrDoubleTeacherVote",
    "HrEvidenceUsage",
]
