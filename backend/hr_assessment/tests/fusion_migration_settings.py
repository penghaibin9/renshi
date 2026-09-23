"""Focused HR12 migration graph rehearsal, not the complete production graph."""
from hr_assessment.tests.fusion_settings import *  # noqa: F401,F403
MIGRATION_MODULES = {**MIGRATION_MODULES}
MIGRATION_MODULES.pop('hr_assessment', None)
