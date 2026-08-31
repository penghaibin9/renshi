"""
hr10_development/models/catalog.py

发展活动类型目录模型（总册 §24）。
Tenant 可覆盖系统内置类型的行为特征。
"""

from django.db import models
from django.utils.translation import gettext_lazy as _

from hr10_development.constants import DevelopmentActivityType
from hr10_development.models.base import DevelopmentTenantModel


class DevelopmentActivityCatalog(DevelopmentTenantModel):
    """
    可扩展发展活动类型目录。

    系统内置 18 种类型；tenant 可覆盖行为特征、禁用或新增类型。
    覆盖保存为 Version，修改后新申请用新版本，历史记录不变。
    """

    activity_type_code = models.CharField(
        max_length=64,
        db_index=True,
        verbose_name=_("活动类型代码"),
    )

    display_name = models.CharField(
        max_length=128,
        verbose_name=_("显示名称"),
    )

    display_name_en = models.CharField(
        max_length=128,
        blank=True,
        default="",
        verbose_name=_("英文名"),
    )

    is_system_builtin = models.BooleanField(
        default=False,
        verbose_name=_("系统内置"),
    )

    category = models.CharField(
        max_length=32,
        db_index=True,
        verbose_name=_("类别归属"),
    )

    # 10 项行为特征（可被 Tenant Policy 覆盖）
    requires_program = models.BooleanField(
        default=True,
        verbose_name=_("需要项目"),
    )
    requires_approval = models.BooleanField(
        default=True,
        verbose_name=_("需要审批"),
    )
    requires_budget = models.BooleanField(
        default=False,
        verbose_name=_("需要预算"),
    )
    requires_leave_check = models.BooleanField(
        default=False,
        verbose_name=_("需要请假检查"),
    )
    requires_completion_evidence = models.BooleanField(
        default=True,
        verbose_name=_("需要完成证据"),
    )
    requires_provider_verification = models.BooleanField(
        default=False,
        verbose_name=_("需要 Provider 核验"),
    )
    can_generate_learning_hours = models.BooleanField(
        default=False,
        verbose_name=_("产生培训学时"),
    )
    can_generate_practice_hours = models.BooleanField(
        default=False,
        verbose_name=_("产生实践时长"),
    )
    can_feed_hr09 = models.BooleanField(
        default=False,
        verbose_name=_("可作 HR09 证据"),
    )
    result_authority = models.CharField(
        max_length=16,
        default="HR10",
        verbose_name=_("结果权威域"),
        help_text="HR10/HR03/HR09",
    )

    # 排序
    sort_order = models.IntegerField(
        default=0,
        verbose_name=_("排序"),
    )

    is_active = models.BooleanField(
        default=True,
        verbose_name=_("启用"),
    )

    class Meta:
        db_table = "hr_development_activity_catalog"
        unique_together = [
            ("tenant_id", "activity_type_code"),
        ]
        verbose_name = _("发展活动类型")
        verbose_name_plural = verbose_name
        ordering = ["sort_order", "activity_type_code"]

    def __str__(self):
        return f"{self.display_name} ({self.activity_type_code})"

    @classmethod
    def seed_builtin_catalog(cls, tenant_id: int):
        """种子内置 18 种活动类型到指定 tenant。"""
        builtins = [
            ("INTERNAL_TRAINING", "校内培训", "Internal Training", "培训",
             True, True, False, False, True, False, True, False, True, "HR10"),
            ("EXTERNAL_TRAINING", "校外培训", "External Training", "培训",
             True, True, True, True, True, True, True, False, True, "HR10"),
            ("ONLINE_LEARNING", "线上学习", "Online Learning", "学习",
             True, False, False, False, True, True, True, False, False, "HR10"),
            ("BLENDED_LEARNING", "混合研修", "Blended Learning", "学习",
             True, True, True, True, True, True, True, False, True, "HR10"),
            ("TEACHING_WORKSHOP", "教学研讨会", "Teaching Workshop", "研讨",
             True, False, False, False, True, False, True, False, True, "HR10"),
            ("DIGITAL_SKILL_TRAINING", "数字化能力培训", "Digital Skill Training", "培训",
             True, True, True, False, True, True, True, False, True, "HR10"),
            ("INDUSTRY_TECH_TRAINING", "产业技术培训", "Industry Tech Training", "培训",
             True, True, True, True, True, True, True, True, True, "HR10"),
            ("SCHOOL_VISIT", "校际参观", "School Visit", "参观",
             False, True, True, True, True, False, False, False, False, "HR10"),
            ("VISITING_STUDY", "访学研修", "Visiting Study", "进修",
             True, True, True, True, True, True, True, False, True, "HR10"),
            ("SHADOWING", "跟岗研修", "Shadowing", "进修",
             True, True, True, True, True, True, True, True, True, "HR10"),
            ("FURTHER_STUDY", "继续教育", "Further Study", "进修",
             True, True, True, True, True, True, True, False, False, "HR10"),
            ("DEGREE_STUDY_PROCESS", "学历提升", "Degree Study Process", "进修",
             True, True, True, True, True, True, False, False, False, "HR03"),
            ("CERTIFICATION_PREPARATION", "证书备考", "Certification Preparation", "学习",
             True, False, False, False, True, True, True, False, False, "HR09"),
            ("ENTERPRISE_PRACTICE", "企业实践", "Enterprise Practice", "企业实践",
             True, True, True, True, True, True, False, True, True, "HR10"),
            ("PRACTICE_BASE_TRAINING", "实践基地培训", "Practice Base Training", "企业实践",
             True, True, True, True, True, True, False, True, True, "HR10"),
            ("RESEARCH_VISIT", "科研访学", "Research Visit", "进修",
             True, True, True, True, True, True, False, False, False, "HR10"),
            ("INTERNATIONAL_EXCHANGE", "国际交流", "International Exchange", "进修",
             True, True, True, True, True, True, True, False, False, "HR10"),
            ("OTHER", "其他", "Other", "其他",
             False, False, False, False, False, False, False, False, False, "HR10"),
        ]

        objects = []
        for idx, (code, name, en_name, cat, req_prog, req_appr, req_bud, req_leave,
                   req_ev, req_pv, lrn_hrs, prac_hrs, feed_h09, authority) in enumerate(builtins):
            objects.append(cls(
                tenant_id=tenant_id,
                activity_type_code=code,
                display_name=name,
                display_name_en=en_name,
                is_system_builtin=True,
                category=cat,
                requires_program=req_prog,
                requires_approval=req_appr,
                requires_budget=req_bud,
                requires_leave_check=req_leave,
                requires_completion_evidence=req_ev,
                requires_provider_verification=req_pv,
                can_generate_learning_hours=lrn_hrs,
                can_generate_practice_hours=prac_hrs,
                can_feed_hr09=feed_h09,
                result_authority=authority,
                sort_order=idx,
            ))
        cls.objects.bulk_create(objects, ignore_conflicts=True)
