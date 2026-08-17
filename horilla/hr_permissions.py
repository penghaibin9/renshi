"""Canonical HR permission semantics and compatibility aliases.

Django normally interprets ``app_label.codename``. The HR domain contract uses
semantic permission codes such as ``hr.staff.view`` and
``hr.development.plan.approve``. Legacy modules may also ship ``hr01.*`` through
``hr18.*`` codes. This module keeps those strings as business contracts while
the authentication backend resolves them against Permission *codenames* inside
the selected tenant.
"""

from __future__ import annotations

import re

CANONICAL_PREFIX_ALIASES = {
    "hr01.": "hr.dashboard.",
    "hr02.": "hr.structure.",
    "hr03.": "hr.staff.",
    "hr04.": "hr.recruitment.",
    "hr05.": "hr.onboarding.",
    "hr06.": "hr.change.",
    "hr07.": "hr.contracts.",
    "hr08.": "hr.external.",
    "hr09.": "hr.qualification.",
    "hr10.": "hr.development.",
    "hr11.": "hr.time.",
    "hr12.": "hr.assessment.",
    "hr13.": "hr.title.",
    "hr14.": "hr.appointment.",
    "hr15.": "hr.payroll.",
    "hr16.": "hr.exit.",
    "hr17.": "hr.self.",
    "hr18.": "hr.data.",
}

_HR_LEGACY_RE = re.compile(r"^hr\d{2}\.")


def is_semantic_hr_permission(code: str) -> bool:
    return bool(code) and (code.startswith("hr.") or bool(_HR_LEGACY_RE.match(code)))


def permission_aliases(code: str) -> frozenset[str]:
    """Return canonical + legacy spellings for one semantic permission code."""
    aliases = {code}
    for legacy_prefix, canonical_prefix in CANONICAL_PREFIX_ALIASES.items():
        if code.startswith(legacy_prefix):
            aliases.add(canonical_prefix + code[len(legacy_prefix) :])
        if code.startswith(canonical_prefix):
            aliases.add(legacy_prefix + code[len(canonical_prefix) :])
    return frozenset(aliases)


def semantic_codes_for_codename(codename: str) -> frozenset[str]:
    if not is_semantic_hr_permission(codename):
        return frozenset()
    return permission_aliases(codename)
