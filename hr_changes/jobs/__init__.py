"""
hr_changes.jobs —— HR06 后台任务包。
"""

from hr_changes.jobs.apply_due_cases import run_due_applications

__all__ = ["run_due_applications"]
