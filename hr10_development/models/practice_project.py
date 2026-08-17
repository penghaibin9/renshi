"""
hr10_development/models/practice_project.py

企业实践项目聚合根（总册 §69/§70/§78）。
15 状态机，MATCHING→READY_TO_START→ACTIVE→COMPLETION_REVIEW。
"""

from django.db import models
from django.utils.translation import gettext_lazy as _
from hr10_development.constants import ProjectLifecycleStatus
from hr10_development.models.base import DevelopmentTenantModel


class HrEnterprisePracticeProject(DevelopmentTenantModel):
    project_no = models.CharField(max_length=64, verbose_name=_("项目编号"))
    title = models.CharField(max_length=256, verbose_name=_("项目标题"))
    specialty_category = models.CharField(max_length=128, blank=True, default="", verbose_name=_("专业大类"))
    provider_org_id = models.BigIntegerField(verbose_name=_("企业/基地 ID"))
    practice_base_ref = models.CharField(max_length=256, blank=True, default="", verbose_name=_("基地引用"))
    owner_org_id = models.BigIntegerField(null=True, blank=True, verbose_name=_("校内主办组织"))
    target_population_rule_id = models.CharField(max_length=128, blank=True, default="")
    current_version_id = models.BigIntegerField(null=True, blank=True)
    lifecycle_status = models.CharField(max_length=32, choices=ProjectLifecycleStatus.choices, default=ProjectLifecycleStatus.DRAFT, db_index=True)
    planned_start_date = models.DateField(null=True, blank=True)
    planned_end_date = models.DateField(null=True, blank=True)
    capacity = models.IntegerField(default=0)
    funding_source_id = models.CharField(max_length=64, blank=True, default="")
    version = models.IntegerField(default=1)

    class Meta:
        db_table = "hr_enterprise_practice_project"
        verbose_name = _("企业实践项目")
        verbose_name_plural = verbose_name
        unique_together = [("tenant_id", "project_no")]
        indexes = [models.Index(fields=["tenant_id", "lifecycle_status"])]


class HrEnterprisePracticeProjectVersion(DevelopmentTenantModel):
    project_id = models.BigIntegerField(db_index=True, verbose_name=_("项目 ID"))
    version_no = models.IntegerField(default=1)
    objectives_json = models.JSONField(default=dict)
    position_scene_requirements_json = models.JSONField(default=dict)
    module_task_json = models.JSONField(default=dict)
    mentor_requirements_json = models.JSONField(default=dict)
    evaluation_rubric_json = models.JSONField(default=dict)
    output_requirements_json = models.JSONField(default=dict)
    safety_requirements_json = models.JSONField(default=dict)
    confidentiality_ip_requirements_json = models.JSONField(default=dict)
    completion_rule_json = models.JSONField(default=dict)
    policy_snapshot_json = models.JSONField(default=dict)
    content_hash = models.CharField(max_length=128, blank=True, default="")
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "hr_enterprise_practice_project_version"
        verbose_name = _("企业实践项目版本")
        verbose_name_plural = verbose_name
        unique_together = [("project_id", "version_no")]
