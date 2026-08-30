"""Formal providers used by HR06 to call other Authority modules."""

from hr_changes.providers.hr03_correction import (
    HR03CorrectionProvider,
    HR03CorrectionProviderError,
)

__all__ = ["HR03CorrectionProvider", "HR03CorrectionProviderError"]
