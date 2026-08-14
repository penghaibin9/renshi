"""Canonical HR permission naming and registration contract.

This module is intentionally framework-light: it defines the stable permission
namespace shared by HR01-HR18. Authentication backends and module policies may
consume it, but they must not invent alternative canonical keys.
"""

from dataclasses import dataclass
import re
from typing import Dict, Iterable, Tuple

HR_DOMAINS = {
    "HR01": "dashboard",
    "HR02": "structure",
    "HR03": "staff",
    "HR04": "recruitment",
    "HR05": "onboarding",
    "HR06": "change",
    "HR07": "contracts",
    "HR08": "external",
    "HR09": "qualification",
    "HR10": "development",
    "HR11": "time",
    "HR12": "assessment",
    "HR13": "title",
    "HR14": "appointment",
    "HR15": "payroll",
    "HR16": "exit",
    "HR17": "self",
    "HR18": "data",
}
DOMAIN_MODULES = {domain: code for code, domain in HR_DOMAINS.items()}
_PERMISSION_RE = re.compile(
    r"^hr\.(?P<domain>[a-z][a-z0-9_]*)\.(?P<action>[a-z][a-z0-9_.:-]*)$"
)


@dataclass(frozen=True)
class PermissionDefinition:
    key: str
    module_code: str
    description: str = ""


class CanonicalPermissionRegistry:
    def __init__(self) -> None:
        self._definitions: Dict[str, PermissionDefinition] = {}

    @staticmethod
    def validate(definition: PermissionDefinition) -> None:
        expected_domain = HR_DOMAINS.get(definition.module_code)
        if expected_domain is None:
            raise ValueError("unknown HR module code: %s" % definition.module_code)
        match = _PERMISSION_RE.match(definition.key)
        if match is None:
            raise ValueError(
                "canonical HR permission must match hr.<domain>.<action>: %s"
                % definition.key
            )
        if match.group("domain") != expected_domain:
            raise ValueError(
                "permission domain %s does not belong to %s (%s)"
                % (match.group("domain"), definition.module_code, expected_domain)
            )

    def register(self, *definitions: PermissionDefinition) -> None:
        for definition in definitions:
            self.validate(definition)
            existing = self._definitions.get(definition.key)
            if existing is not None and existing != definition:
                raise ValueError("permission already registered: %s" % definition.key)
            self._definitions[definition.key] = definition

    def get(self, key: str) -> PermissionDefinition:
        try:
            return self._definitions[key]
        except KeyError:
            raise KeyError("unregistered canonical HR permission: %s" % key)

    def contains(self, key: str) -> bool:
        return key in self._definitions

    def all(self) -> Tuple[PermissionDefinition, ...]:
        return tuple(self._definitions[key] for key in sorted(self._definitions))


permission_registry = CanonicalPermissionRegistry()


def register_permissions(definitions: Iterable[PermissionDefinition]) -> None:
    permission_registry.register(*tuple(definitions))
