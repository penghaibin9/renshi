"""Durable HR12 rollout flags derived from tenant cutover Authority state.

These are compatibility reads for existing callers. They are not mutable cache
flags: the only write boundary is the ``cutover`` management command, which
persists current state and an append-only phase event in the database.
"""

from __future__ import annotations


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

AUTHORITY_FLAGS = frozenset(
    {
        "HR12_POLICY_AUTHORITY",
        "HR12_CYCLE_AUTHORITY",
        "HR12_GOAL_AUTHORITY",
        "HR12_ANNUAL_AUTHORITY",
        "HR12_TERM_AUTHORITY",
        "HR12_ETHICS_AUTHORITY",
    }
)
AUTHORITY_PHASES = frozenset(
    {
        "NEW_AUTHORITY",
        "LEGACY_READONLY_PROJECTION",
        "POST_CUTOVER_CLEANUP",
    }
)


def _state(tenant_id: int) -> tuple[str, str]:
    if not tenant_id:
        raise ValueError("tenant_id is required for HR12 feature state")

    from hr_assessment.models import HrAssessmentCutoverEvent
    from hr_control_center.models import HrAuthorityCutover

    cutover = HrAuthorityCutover.objects.filter(
        tenant_id=tenant_id,
        domain=HrAuthorityCutover.Domain.ASSESSMENT,
    ).first()
    phase = (
        HrAssessmentCutoverEvent.objects.filter(tenant_id=tenant_id)
        .order_by("-occurred_at", "-id")
        .values_list("phase", flat=True)
        .first()
        or ""
    )
    mode = cutover.mode if cutover is not None else HrAuthorityCutover.Mode.LEGACY_ONLY
    return mode, phase


def get_flag(name: str, *, tenant_id: int) -> bool:
    if name not in DEFAULTS:
        raise ValueError(f"Unknown feature flag: {name}")
    mode, phase = _state(tenant_id)

    from hr_control_center.models import HrAuthorityCutover

    if name in AUTHORITY_FLAGS:
        return mode == HrAuthorityCutover.Mode.AUTHORITY_ONLY
    if name == "HR12_SHADOW_EXECUTION":
        return phase == "SHADOW_EXECUTION"
    if name == "HR12_NEW_CYCLE_ONLY":
        return phase in AUTHORITY_PHASES
    return False


def set_flag(name: str, value: bool, *, tenant_id: int | None = None) -> None:
    """Reject ad-hoc mutation; use the ordered durable cutover workflow."""
    raise RuntimeError(
        "HR12 feature state is derived from durable cutover records; "
        "use `manage.py cutover --tenant-id ... --phase ...`"
    )


def list_flags(*, tenant_id: int) -> dict:
    return {name: get_flag(name, tenant_id=tenant_id) for name in DEFAULTS}


def ensure_no_double_authority(active_domain: str, *, tenant_id: int) -> bool:
    """HR12 Authority and shadow execution must never be active together."""
    if active_domain == "HR12":
        return not get_flag("HR12_SHADOW_EXECUTION", tenant_id=tenant_id)
    return True
