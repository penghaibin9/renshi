"""
hr_external/models/title_qualification.py 鈥斺€?绉板彿浠诲懡 + 鑱樼敤璧勬牸瀹℃煡 + 灞ヨ亴璇勪环锛堟€诲唽 搂14/搂5.2/搂35/搂71锛夈€?

S2/S4/S5 缂哄け妯″瀷琛ラ綈锛?
- HrExternalTitleAppointment锛氱О鍙蜂换鍛斤紙Title 鈮?Engagement锛岃崳瑾夋€хО鍙蜂笌鍙楄仒鍒嗙锛?
- HrExternalQualificationReview锛氳仒鐢ㄨ祫鏍煎鏌ワ紙搂35 瀹℃壒鍓嶆鏌ワ紝璇?HR09 宸叉牳楠屼簨瀹烇級
- HrExternalPerformanceReview锛氬鑱樺饱鑱岃瘎浠凤紙搂71锛岀画鑱樺喅绛栬緭鍏ワ級
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from hr_external.constants import (
    ExternalTitleAppointmentType,
    PerformanceResult,
    QualificationReviewStatus,
)


class HrExternalTitleAppointment(models.Model):
    """绉板彿浠诲懡锛埪?.2/搂14/搂15锛夈€傝崳瑾夌О鍙蜂笌 Engagement 鍒嗙锛?
    HONORARY_TITLE 涓嶈嚜鍔ㄦ剰鍛崇潃鏈夎/宸ヨ祫/闂ㄧ/OA/鏁欏姟鏉冮檺銆?""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    person_id = models.ForeignKey(
        "hr_staff.HrPerson",
        on_delete=models.PROTECT,
        related_name="external_title_appointments",
    )
    external_profile_id = models.ForeignKey(
        "hr_external.HrExternalTeacherProfile",
        on_delete=models.PROTECT,
        related_name="title_appointments",
    )
    title_type = models.CharField(
        max_length=32,
        choices=ExternalTitleAppointmentType.choices,
        default=ExternalTitleAppointmentType.OTHER,
    )
    title_name = models.CharField(max_length=200)
    conferring_authority = models.CharField(max_length=200, blank=True, default="")
    conferred_at = models.DateField(null=True, blank=True)
    valid_from = models.DateField(null=True, blank=True)
    valid_to = models.DateField(null=True, blank=True)
    is_honorary_only = models.BooleanField(
        default=False,
        help_text="绾崳瑾夌О鍙凤紙涓嶉粯璁ゅ紑鏀捐/宸ヨ祫/闂ㄧ/鏁欏姟鏉冮檺锛?,
    )
    version = models.BigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("HR External Title Appointment")
        verbose_name_plural = _("HR External Title Appointments")
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "person_id", "title_type", "valid_from"],
                name="uniq_hr_external_title_appt",
            ),
            models.CheckConstraint(
                condition=models.Q(version__gte=1),
                name="hex_title_appt_version_gte_1",
            ),
        ]
        indexes = [
            models.Index(
                fields=["tenant_id", "person_id", "title_type"],
                name="hex_title_appt_person_idx",
            ),
            models.Index(
                fields=["tenant_id", "is_honorary_only"],
                name="hex_title_appt_honorary_idx",
            ),
        ]

    def __str__(self):
        return f"[{self.tenant_id}] {self.title_type} {self.title_name}"


class HrExternalQualificationReview(models.Model):
    """鑱樼敤璧勬牸瀹℃煡锛埪?5/搂14锛夈€傝 HR09 宸叉牳楠屼簨瀹烇紱鏃犲垯 staging evidence 鎻愪氦鏍搁獙锛埪?0锛夈€?""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    person_id = models.ForeignKey(
        "hr_staff.HrPerson",
        on_delete=models.PROTECT,
        related_name="external_qualification_reviews",
    )
    case_id = models.ForeignKey(
        "hr_external.HrExternalHiringCase",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="qualification_reviews",
    )
    status = models.CharField(
        max_length=24,
        choices=QualificationReviewStatus.choices,
        default=QualificationReviewStatus.PENDING,
    )
    # 寮曠敤 HR09 鏉冨▉璧勬牸浜嬪疄锛坧rovider 鍗犱綅锛汬R09 鏈氦浠樺垯绌猴級
    hr09_credential_ref = models.CharField(max_length=64, blank=True, default="")
    # 鏆傚瓨寰呮牳楠岃瘉鎹紙鏉愭枡寮曠敤鍒楄〃锛?
    staging_evidence = models.JSONField(default=list, blank=True)
    reviewer = models.BigIntegerField(null=True, blank=True)
    review_notes = models.TextField(blank=True, default="")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    version = models.BigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("HR External Qualification Review")
        verbose_name_plural = _("HR External Qualification Reviews")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(version__gte=1),
                name="hex_qual_version_gte_1",
            ),
        ]
        indexes = [
            models.Index(
                fields=["tenant_id", "person_id", "status"],
                name="hex_qual_person_idx",
            ),
            models.Index(
                fields=["tenant_id", "case_id", "status"],
                name="hex_qual_case_idx",
            ),
        ]

    def __str__(self):
        return f"[{self.tenant_id}] qual review {self.status}"


class HrExternalPerformanceReview(models.Model):
    """灞ヨ亴璇勪环锛埪?4/搂71锛夈€傜画鑱樺喅绛栧叧閿緭鍏ワ紱璇勪环缁撴灉涓嶅彲鍘熷湴鏀癸紙00 搂20 FINAL 鍚庝笉鍙彉鏇达級銆?""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.BigIntegerField(db_index=True)
    engagement_id = models.ForeignKey(
        "hr_external.HrExternalEngagement",
        on_delete=models.PROTECT,
        related_name="performance_reviews",
    )
    period = models.CharField(max_length=64)
    task_completion = models.TextField(blank=True, default="")
    teaching_quality_ref = models.CharField(max_length=64, blank=True, default="")
    host_org_rating = models.CharField(max_length=16, blank=True, default="")  # 1-5 鎴栧瓧鍏?
    compliance_result = models.CharField(max_length=32, blank=True, default="")
    contribution_summary = models.TextField(blank=True, default="")
    result = models.CharField(
        max_length=24,
        choices=PerformanceResult.choices,
        blank=True,
        default="",
    )
    reviewer = models.BigIntegerField(null=True, blank=True)
    finalized_at = models.DateTimeField(null=True, blank=True)
    version = models.BigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("HR External Performance Review")
        verbose_name_plural = _("HR External Performance Reviews")
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "engagement_id", "period"],
                name="uniq_hr_external_perf_period",
            ),
            models.CheckConstraint(
                condition=models.Q(version__gte=1),
                name="hex_perf_version_gte_1",
            ),
        ]
        indexes = [
            models.Index(
                fields=["tenant_id", "engagement_id", "result"],
                name="hex_perf_eng_result_idx",
            ),
            models.Index(
                fields=["tenant_id", "result"],
                name="hex_perf_result_idx",
            ),
        ]

    def __str__(self):
        return f"[{self.tenant_id}] perf {self.period} {self.result}"
