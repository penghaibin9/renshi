"""Isolated migration-replay settings. Never select for the deployed application."""
from .sqlite_settings import *  # noqa
import os
MIGRATION_MODULES={**MIGRATION_MODULES,"hr_payroll":"hr_payroll.migrations"}
DATABASES={"default":{"ENGINE":"django.db.backends.sqlite3","NAME":os.environ.get("HR15_MIGRATION_TEST_DB",":memory:")}}
