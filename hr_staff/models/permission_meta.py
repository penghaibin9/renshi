"""
hr_staff/models/permission_meta.py —— HR03 权限码注册（总册 §39）。

仿 hr_control_center.HrControlCenterPermissionMeta：managed=False，仅注册 permissions。
"""

from django.db import models


class HrStaffPermissionMeta(models.Model):
    """仅为注册 HR03 权限码（总册 §39），无数据字段。"""

    class Meta:
        managed = False
        permissions = (
            ("hr.staff.view", "HR Staff: View"),
            ("hr.staff.view_sensitive", "HR Staff: View Sensitive"),
            ("hr.staff.reveal_high_sensitive", "HR Staff: Reveal High Sensitive"),
            ("hr.staff.create", "HR Staff: Create"),
            ("hr.staff.edit_basic", "HR Staff: Edit Basic"),
            ("hr.staff.export", "HR Staff: Export"),
            ("hr.staff.export_sensitive", "HR Staff: Export Sensitive"),
            ("hr.staff.import", "HR Staff: Import"),
            ("hr.staff.assignment.view", "HR Staff: View Assignment"),
            ("hr.staff.assignment.correct", "HR Staff: Correct Assignment"),
            ("hr.staff.background.view", "HR Staff: View Background"),
            ("hr.staff.background.manage", "HR Staff: Manage Background"),
            ("hr.staff.material.view", "HR Staff: View Material"),
            ("hr.staff.material.upload", "HR Staff: Upload Material"),
            ("hr.staff.material.verify", "HR Staff: Verify Material"),
            ("hr.staff.material.download_sensitive", "HR Staff: Download Sensitive Material"),
            ("hr.staff.correction.view", "HR Staff: View Correction"),
            ("hr.staff.correction.create", "HR Staff: Create Correction"),
            ("hr.staff.correction.review", "HR Staff: Review Correction"),
            ("hr.staff.correction.approve_high_risk", "HR Staff: Approve High Risk Correction"),
            ("hr.staff.audit.view", "HR Staff: View Audit"),
            ("hr.staff.data_quality.manage", "HR Staff: Manage Data Quality"),
            ("hr.staff.personnel_decision.view", "HR Staff: View Personnel Decision"),
            ("hr.staff.personnel_decision.manage", "HR Staff: Manage Personnel Decision"),
            ("hr.staff.reward_disciplinary.view", "HR Staff: View Reward / Disciplinary"),
            ("hr.staff.reward_disciplinary.manage", "HR Staff: Manage Reward / Disciplinary"),
        )
