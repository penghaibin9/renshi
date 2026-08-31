"""
hr_qualification/services/__init__.py —— HR09 服务层统一导出。
"""

from hr_qualification.services.application_service import ApplicationError, ApplicationService
from hr_qualification.services.credential_service import CredentialError, CredentialService
from hr_qualification.services.evidence_service import EvidenceAggregationService
from hr_qualification.services.precheck_service import PrecheckItem, PrecheckResult, PrecheckService
from hr_qualification.services.legacy_projection import LegacyQualificationProjection
from hr_qualification.services.recheck_service import RecheckError, RecheckService
from hr_qualification.services.requirement_service import RequirementMatchItem, RequirementService
from hr_qualification.services.review_service import ReviewError, ReviewService
from hr_qualification.services.risk_service import RiskService
from hr_qualification.services.rule_service import RulePackError, RuleService
from hr_qualification.services.verification_service import VerificationService

__all__ = [
    "ApplicationError",
    "ApplicationService",
    "CredentialError",
    "CredentialService",
    "EvidenceAggregationService",
    "LegacyQualificationProjection",
    "PrecheckItem",
    "PrecheckResult",
    "PrecheckService",
    "RecheckError",
    "RecheckService",
    "RequirementMatchItem",
    "RequirementService",
    "ReviewError",
    "ReviewService",
    "RiskService",
    "RulePackError",
    "RuleService",
    "VerificationService",
]
