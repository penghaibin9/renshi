"""HR12 Assessment — Feature Flags (S1)。用于 rollout/shadow/UI entry，禁止同时存在两个 formal write authority。"""

from django.core.cache import cache

FLAG_NAMESPACE = "hr12_feature_flags"

DEFAULTS = {
    "HR12_POLICY_AUTHORITY": False,
    "HR12_CYCLE_AUTHORITY": False,
    "HR12_GOAL_AUTHORITY": False,
    "HR12_ANNUAL_AUTHORITY": False,
    "HR12_TERM_AUTHORITY": False,
    "HR12_ETHICS_AUTHORITY": False,
    "HR12_SHADOW_EXECUTION": False,
    "HR12_NEW_CYCLE_ONLY": False,
}


def _key(name: str) -> str:
    return f"{FLAG_NAMESPACE}:{name}"


def get_flag(name: str) -> bool:
    if name not in DEFAULTS:
        return False
    return bool(cache.get(_key(name)) or DEFAULTS[name])


def set_flag(name: str, value: bool) -> None:
    if name not in DEFAULTS:
        raise ValueError(f"Unknown feature flag: {name}")
    cache.set(_key(name), value, timeout=None)


def list_flags() -> dict:
    return {name: get_flag(name) for name in DEFAULTS}


def ensure_no_double_authority(active_domain: str) -> bool:
    """禁止同时拥有两个 formal write authority。S12 切后调用。"""
    if active_domain == "HR12":
        return not get_flag("HR12_SHADOW_EXECUTION")
    return True
