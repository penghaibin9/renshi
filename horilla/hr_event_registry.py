"""Global HR business-event registration contract.

This is deliberately separate from ``horilla_audit.registry``. Auditlog model
registration answers "which model changes are audited"; this registry answers
"which versioned business events are valid cross-domain contracts".
"""

from dataclasses import dataclass
import re
from typing import Dict, Iterable, Tuple

from horilla.hr_permission_registry import HR_DOMAINS

_EVENT_RE = re.compile(
    r"^hr\.(?P<domain>[a-z][a-z0-9_]*)\."
    r"(?P<aggregate>[a-z][a-z0-9_]*)\."
    r"(?P<verb>[a-z][a-z0-9_]*)$"
)


@dataclass(frozen=True)
class BusinessEventDefinition:
    name: str
    module_code: str
    aggregate: str
    version: int = 1
    description: str = ""


class GlobalEventRegistry:
    def __init__(self) -> None:
        self._definitions: Dict[Tuple[str, int], BusinessEventDefinition] = {}

    @staticmethod
    def validate(definition: BusinessEventDefinition) -> None:
        expected_domain = HR_DOMAINS.get(definition.module_code)
        if expected_domain is None:
            raise ValueError("unknown HR module code: %s" % definition.module_code)
        if not isinstance(definition.version, int) or definition.version < 1:
            raise ValueError("business event version must be a positive integer")
        match = _EVENT_RE.match(definition.name)
        if match is None:
            raise ValueError(
                "canonical HR event must match hr.<domain>.<aggregate>.<verb>: %s"
                % definition.name
            )
        if match.group("domain") != expected_domain:
            raise ValueError(
                "event domain %s does not belong to %s (%s)"
                % (match.group("domain"), definition.module_code, expected_domain)
            )
        if match.group("aggregate") != definition.aggregate:
            raise ValueError(
                "event aggregate mismatch: %s != %s"
                % (match.group("aggregate"), definition.aggregate)
            )

    def register(self, *definitions: BusinessEventDefinition) -> None:
        for definition in definitions:
            self.validate(definition)
            identity = (definition.name, definition.version)
            existing = self._definitions.get(identity)
            if existing is not None and existing != definition:
                raise ValueError(
                    "business event already registered: %s@v%s"
                    % (definition.name, definition.version)
                )
            self._definitions[identity] = definition

    def get(self, name: str, version: int = 1) -> BusinessEventDefinition:
        identity = (name, version)
        try:
            return self._definitions[identity]
        except KeyError:
            raise KeyError(
                "unregistered HR business event: %s@v%s" % (name, version)
            )

    def contains(self, name: str, version: int = 1) -> bool:
        return (name, version) in self._definitions

    def all(self) -> Tuple[BusinessEventDefinition, ...]:
        return tuple(
            self._definitions[key]
            for key in sorted(self._definitions, key=lambda item: (item[0], item[1]))
        )


global_event_registry = GlobalEventRegistry()


def register_business_events(definitions: Iterable[BusinessEventDefinition]) -> None:
    global_event_registry.register(*tuple(definitions))
