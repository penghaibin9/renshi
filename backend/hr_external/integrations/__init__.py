"""hr_external.integrations —— HR08 跨域 Provider 契约（00 §13/§14）。

- hr03.py    HR03 Person/StaffMaster（真实实现，复用 hr_staff 服务）
- hr07.py    HR07 正式合同权威适配器
- academic.py 教务系统可配置 HTTP 适配器（缺配置时明确 UNAVAILABLE）
- iam.py     统一身份权限可配置 HTTP 适配器（缺配置时明确 UNAVAILABLE）
- hr15.py    HR15 不可变结算依据接收适配器
Package-level exports are resolved lazily.  Consumers that only need the base
contract must not import every optional HR authority and its models.
"""

from importlib import import_module


_EXPORTS = {
    "PersonProvider": ("hr_external.integrations.hr03", "PersonProvider"),
    "StaffMasterProvider": (
        "hr_external.integrations.hr03",
        "StaffMasterProvider",
    ),
    "AgreementProvider": ("hr_external.integrations.hr07", "AgreementProvider"),
    "AcademicProvider": ("hr_external.integrations.academic", "AcademicProvider"),
    "IamProvisioningProvider": (
        "hr_external.integrations.iam",
        "IamProvisioningProvider",
    ),
    "SettlementProvider": ("hr_external.integrations.hr15", "SettlementProvider"),
}

__all__ = [
    "PersonProvider",
    "StaffMasterProvider",
    "AgreementProvider",
    "AcademicProvider",
    "IamProvisioningProvider",
    "SettlementProvider",
]


def __getattr__(name):
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute_name = target
    value = getattr(import_module(module_name), attribute_name)
    globals()[name] = value
    return value
