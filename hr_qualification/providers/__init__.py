"""
hr_qualification/providers/__init__.py —— HR09 Provider 层统一导出。
"""

from hr_qualification.providers.base import (
    HrEvidenceProvider,
    ProviderError,
    ProviderEvidenceItem,
    ProviderEvidenceResult,
)
from hr_qualification.providers.hr03 import Hr03EducationProvider, Hr03WorkHistoryProvider
from hr_qualification.providers.hr08 import Hr08EngagementProvider
from hr_qualification.providers.hr09 import Hr09CredentialProvider
from hr_qualification.providers.hr10 import (
    AcademicTeachingProvider,
    Hr10EnterprisePracticeProvider,
    Hr10TrainingProvider,
)
from hr_qualification.providers.hr12 import Hr12AssessmentProvider, ResearchProjectProvider

__all__ = [
    "AcademicTeachingProvider",
    "Hr03EducationProvider",
    "Hr03WorkHistoryProvider",
    "Hr08EngagementProvider",
    "Hr09CredentialProvider",
    "Hr10EnterprisePracticeProvider",
    "Hr10TrainingProvider",
    "Hr12AssessmentProvider",
    "ResearchProjectProvider",
    "HrEvidenceProvider",
    "ProviderError",
    "ProviderEvidenceItem",
    "ProviderEvidenceResult",
]
