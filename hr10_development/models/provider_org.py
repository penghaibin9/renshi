"""
hr10_development/models/provider_org.py

培训/实践提供机构模型（总册 §25/§44/§71）。
统一管理培训机构、企业、实践基地等外部组织。
"""

from django.db import models
from django.utils.translation import gettext_lazy as _

from hr10_development.constants import (
    ProviderKind,
    ProviderVerificationStatus,
    PracticeBaseLevel,
    RiskStatus,
)
from hr10_development.models.base import DevelopmentTenantModel


class HrDevelopmentProviderOrganization(DevelopmentTenantModel):
    """
    培训/实践提供机构。

    不用于内部主办培训（通过 owner_org_id 引用 HR02 Organization）。
    项目发布时冻结 provider snapshot。
    """

    provider_code = models.CharField(
        max_length=64,
        verbose_name=_("机构编码"),
    )

    provider_kind = models.CharField(
        max_length=32,
        choices=ProviderKind.choices,
        db_index=True,
        verbose_name=_("机构类型"),
    )

    legal_name = models.CharField(
        max_length=256,
        verbose_name=_("法人全称"),
    )

    short_name = models.CharField(
        max_length=128,
        blank=True,
        default="",
        verbose_name=_("简称"),
    )

    unified_social_credit_code_hash = models.CharField(
        max_length=128,
        blank=True,
        default="",
        verbose_name=_("统一社会信用代码(SHA256)"),
    )

    # Verification
    verification_status = models.CharField(
        max_length=32,
        choices=ProviderVerificationStatus.choices,
        default=ProviderVerificationStatus.PENDING,
        db_index=True,
        verbose_name=_("核验状态"),
    )

    verified_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("核验时间"),
    )

    valid_from = models.DateField(
        null=True,
        blank=True,
        verbose_name=_("有效期起"),
    )

    valid_to = models.DateField(
        null=True,
        blank=True,
        verbose_name=_("有效期止"),
    )

    qualification_summary = models.TextField(
        blank=True,
        default="",
        verbose_name=_("资质摘要"),
    )

    # Practice base extension
    practice_base_level = models.CharField(
        max_length=32,
        choices=PracticeBaseLevel.choices,
        blank=True,
        default="",
        verbose_name=_("实践基地级别"),
    )

    official_reference = models.CharField(
        max_length=256,
        blank=True,
        default="",
        verbose_name=_("官方批准文号"),
    )

    specialty_scope_json = models.JSONField(
        blank=True,
        default=dict,
        verbose_name=_("专业服务范围"),
    )

    service_scope_json = models.JSONField(
        blank=True,
        default=dict,
        verbose_name=_("服务范围"),
    )

    # Risk
    risk_status = models.CharField(
        max_length=32,
        choices=RiskStatus.choices,
        default=RiskStatus.LOW,
        db_index=True,
        verbose_name=_("风险状态"),
    )

    risk_notes = models.TextField(
        blank=True,
        default="",
        verbose_name=_("风险备注"),
    )

    last_risk_review = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("最近风险审查"),
    )

    # Contact (no full PII)
    contact_person_display = models.CharField(
        max_length=128,
        blank=True,
        default="",
        verbose_name=_("联系人(显示)"),
    )

    contact_ref = models.CharField(
        max_length=256,
        blank=True,
        default="",
        verbose_name=_("联系方式引用"),
    )

    address_summary = models.TextField(
        blank=True,
        default="",
        verbose_name=_("地址摘要"),
    )

    emergency_contact = models.CharField(
        max_length=256,
        blank=True,
        default="",
        verbose_name=_("紧急联系人"),
    )

    safety_contact = models.CharField(
        max_length=256,
        blank=True,
        default="",
        verbose_name=_("安全联系人"),
    )

    # Metadata
    source = models.CharField(
        max_length=32,
        default="MANUAL",
        verbose_name=_("来源"),
    )

    version = models.IntegerField(
        default=1,
        verbose_name=_("版本(乐观锁)"),
    )

    class Meta:
        db_table = "hr_development_provider_organization"
        unique_together = [
            ("tenant_id", "provider_code"),
        ]
        verbose_name = _("培训/实践提供机构")
        verbose_name_plural = verbose_name
        indexes = [
            models.Index(fields=["tenant_id", "verification_status"], name="hr_dev_prov_verif_idx"),
            models.Index(fields=["tenant_id", "risk_status"], name="hr_dev_prov_risk_idx"),
            models.Index(fields=["tenant_id", "provider_kind"], name="hr_dev_prov_kind_idx"),
        ]

    def __str__(self):
        return f"{self.short_name or self.legal_name} ({self.provider_code})"
