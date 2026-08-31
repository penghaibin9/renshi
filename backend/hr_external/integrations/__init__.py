"""hr_external.integrations —— HR08 跨域 Provider 契约（00 §13/§14）。

- hr03.py    HR03 Person/StaffMaster（真实实现，复用 hr_staff 服务）
- hr07.py    HR07 Agreement（# [总控占位] HR07 未交付）
- academic.py 教务（# [总控占位] 未接入）
- iam.py     IAM（# [总控占位] 未接入）
- hr15.py    HR15 结算（# [总控占位] HR15 未交付）
"""

from hr_external.integrations.academic import AcademicProvider
from hr_external.integrations.hr03 import PersonProvider, StaffMasterProvider
from hr_external.integrations.hr07 import AgreementProvider
from hr_external.integrations.hr15 import SettlementProvider
from hr_external.integrations.iam import IamProvisioningProvider

__all__ = [
    "PersonProvider",
    "StaffMasterProvider",
    "AgreementProvider",
    "AcademicProvider",
    "IamProvisioningProvider",
    "SettlementProvider",
]
