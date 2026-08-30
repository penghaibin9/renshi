"""Runtime registry for isolated HR01 todo providers."""

from __future__ import annotations

from typing import Type

from hr_control_center.providers.todo_base import HrTodoProvider


class TodoProviderRegistry:
    def __init__(self):
        self._provider_types: dict[str, Type[HrTodoProvider]] = {}

    def register(self, provider_type: Type[HrTodoProvider]) -> None:
        key = str(getattr(provider_type, "provider_key", "") or "")
        if not key or key == "base":
            raise ValueError("todo provider must declare a stable provider_key")
        existing = self._provider_types.get(key)
        if existing is not None and existing is not provider_type:
            raise ValueError(f"todo provider already registered: {key}")
        self._provider_types[key] = provider_type

    def create_all(self) -> tuple[HrTodoProvider, ...]:
        return tuple(
            self._provider_types[key]() for key in sorted(self._provider_types)
        )

    def keys(self) -> tuple[str, ...]:
        return tuple(sorted(self._provider_types))


todo_provider_registry = TodoProviderRegistry()


def register_todo_provider(provider_type: Type[HrTodoProvider]) -> None:
    todo_provider_registry.register(provider_type)
