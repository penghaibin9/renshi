"""HR07 恢复门禁。

该模块只检查仓库结构是否已经具备“可注册 Django app”的最低条件，
不会创建模型、不会伪造 migration，也不会把 INCOMPLETE 自动改成 READY。
"""

from __future__ import annotations

from pathlib import Path

from hr_contracts import module_contract


REQUIRED_CORE_PATHS = (
    "apps.py",
    "models.py",
    "migrations",
    "tests",
)


def recovery_snapshot(base_dir: Path | None = None) -> dict:
    root = base_dir or Path(__file__).resolve().parent
    present = {name: (root / name).exists() for name in REQUIRED_CORE_PATHS}
    missing = [name for name, exists in present.items() if not exists]
    return {
        "module": module_contract.MODULE_CODE,
        "recoveryState": module_contract.RECOVERY_STATE,
        "safeToRegisterFlag": module_contract.SAFE_TO_REGISTER,
        "present": present,
        "missing": missing,
        "registrationAllowed": (
            not missing
            and module_contract.RECOVERY_STATE == "READY"
            and module_contract.SAFE_TO_REGISTER is True
        ),
    }


def assert_recovery_gate_consistent(base_dir: Path | None = None) -> dict:
    """仓库仍缺核心部件时，禁止误把 SAFE_TO_REGISTER 打开。"""
    snapshot = recovery_snapshot(base_dir=base_dir)
    if snapshot["missing"] and module_contract.SAFE_TO_REGISTER:
        raise RuntimeError(
            "HR07 recovery gate is inconsistent: core parts are missing but "
            "SAFE_TO_REGISTER=True"
        )
    return snapshot
