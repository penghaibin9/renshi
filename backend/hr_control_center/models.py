"""
hr_control_center/models.py

HR01 持久表（总册 21 节）——尽量不复制业务事实，仅确有必要：

- HrAlertInstance:     预警实例（记录“预警”，不复制合同/人员事实）
- HrAuthorityCutover:  Legacy/Authority 切换记录（tenant/domain 级）
- HrDashboardPreference: 用户工作台偏好
"""

from django.db import models
from django.utils.translation import gettext_lazy as _

from horilla.models import HorillaModel


class HrControlCenterPermissionMeta(models.Model):
    """仅为注册 HR01 权限码（总册 6.2），无数据字段。"""

    class Meta:
        managed = False
        permissions = (
            ("hr.dashboard.view", "HR Dashboard: View"),
            ("hr.dashboard.overview.view", "HR Dashboard: View Overview"),
            ("hr.dashboard.todo.view", "HR Dashboard: View Todos"),
            ("hr.dashboard.todo.supervise", "HR Dashboard: Supervise Todos"),
            ("hr.dashboard.alert.view", "HR Dashboard: View Alerts"),
            ("hr.dashboard.alert.manage", "HR Dashboard: Manage Alerts"),
            ("hr.dashboard.workforce.view", "HR Dashboard: View Workforce"),
            ("hr.dashboard.workforce.drilldown", "HR Dashboard: Workforce Drilldown"),
            ("hr.dashboard.quick_action.use", "HR Dashboard: Use Quick Actions"),
            ("hr.dashboard.export", "HR Dashboard: Export"),
            ("hr.dashboard.sensitive_metrics.view", "HR Dashboard: View Sensitive Metrics"),
        )


class HrAlertInstance(HorillaModel):
    """人事预警实例（总册 11.3）。"""

    class Severity(models.TextChoices):
        CRITICAL = "CRITICAL", _("Critical")
        HIGH = "HIGH", _("High")
        MEDIUM = "MEDIUM", _("Medium")
        LOW = "LOW", _("Low")
        INFO = "INFO", _("Info")

    class Status(models.TextChoices):
        OPEN = "OPEN", _("Open")
        ACKNOWLEDGED = "ACKNOWLEDGED", _("Acknowledged")
        SNOOZED = "SNOOZED", _("Snoozed")
        RESOLVED = "RESOLVED", _("Resolved")
        EXPIRED = "EXPIRED", _("Expired")

    tenant_id = models.BigIntegerField(db_index=True)
    alert_key = models.CharField(max_length=64)
    source_domain = models.CharField(max_length=64)
    source_object_type = models.CharField(max_length=64, blank=True, default="")
    source_object_id = models.CharField(max_length=64, blank=True, default="")
    dedupe_key = models.CharField(max_length=255, db_index=True)
    title = models.CharField(max_length=255)
    summary = models.TextField(blank=True, default="")
    severity = models.CharField(max_length=16, choices=Severity.choices, default=Severity.MEDIUM)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.OPEN, db_index=True)
    first_seen_at = models.DateTimeField()
    last_seen_at = models.DateTimeField()
    due_at = models.DateTimeField(null=True, blank=True)
    owner_role = models.CharField(max_length=64, blank=True, default="")
    owner_user_id = models.BigIntegerField(null=True, blank=True)
    payload_json = models.JSONField(default=dict, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_reason = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        verbose_name = _("HR Alert Instance")
        verbose_name_plural = _("HR Alert Instances")
        constraints = [
            # 活跃态逻辑唯一：同一 dedupe_key 在 OPEN/ACKNOWLEDGED/SNOOZED
            # 之间流转时仍只能有一条实例。MySQL 的物理兜底由 0003 迁移用
            # generated column + unique index 实现。
            models.UniqueConstraint(
                fields=["tenant_id", "dedupe_key"],
                condition=models.Q(status__in=["OPEN", "ACKNOWLEDGED", "SNOOZED"]),
                name="uniq_hr_alert_open_dedupe",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant_id", "status", "severity"]),
            models.Index(fields=["tenant_id", "due_at"]),
        ]

    def __str__(self):
        return f"[{self.severity}] {self.title}"


class HrAuthorityCutover(HorillaModel):
    """Legacy/Authority 三阶段切换记录（总册 30.4）。"""

    class Mode(models.TextChoices):
        LEGACY_ONLY = "LEGACY_ONLY", _("Legacy Only")
        DUAL_READ_COMPARE = "DUAL_READ_COMPARE", _("Dual Read Compare")
        AUTHORITY_ONLY = "AUTHORITY_ONLY", _("Authority Only")

    class Domain(models.TextChoices):
        ORGANIZATION = "ORGANIZATION", _("Organization")
        STAFF = "STAFF", _("Staff")

    tenant_id = models.BigIntegerField(db_index=True)
    domain = models.CharField(max_length=32, choices=Domain.choices)
    mode = models.CharField(max_length=32, choices=Mode.choices, default=Mode.LEGACY_ONLY)
    cutover_at = models.DateTimeField(auto_now=True)
    cutover_by = models.CharField(max_length=128, blank=True, default="")
    reason = models.CharField(max_length=255)
    source_snapshot_hash = models.CharField(max_length=64, blank=True, default="")
    mapping_version = models.CharField(max_length=32, blank=True, default="DRAFT_V1")
    verification_report_id = models.CharField(max_length=64, blank=True, default="")

    class Meta:
        verbose_name = _("HR Authority Cutover")
        verbose_name_plural = _("HR Authority Cutovers")
        unique_together = ("tenant_id", "domain")

    def __str__(self):
        return f"tenant={self.tenant_id} domain={self.domain} → {self.mode}"


class HrDashboardPreference(HorillaModel):
    """用户工作台偏好（总册 21.1）。"""

    tenant_id = models.BigIntegerField(db_index=True)
    user_id = models.BigIntegerField()
    pinned_metric_keys = models.JSONField(default=list, blank=True)
    quick_action_keys = models.JSONField(default=list, blank=True)
    default_period = models.CharField(max_length=16, blank=True, default="month")
    layout_version = models.CharField(max_length=8, default="1")

    class Meta:
        verbose_name = _("HR Dashboard Preference")
        verbose_name_plural = _("HR Dashboard Preferences")
        unique_together = ("tenant_id", "user_id")

    def __str__(self):
        return f"tenant={self.tenant_id} user={self.user_id}"
