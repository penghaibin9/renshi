"""Test AppConfig that loads the unmanaged permission declaration for drift parity."""

from hr_onboarding.apps import HrOnboardingConfig


class HrOnboardingMiniConfig(HrOnboardingConfig):
    def ready(self):
        super().ready()
        from hr_onboarding import permissions  # noqa: F401
