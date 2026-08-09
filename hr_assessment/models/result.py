"""HR12 — Result / Decision / Archive 模型 (S9)。

总册 §86-102 + §254:
- HrCalibrationSession / HrCalibrationRevision
- HrAssessmentDecisionSession
- HrFinalAssessmentResult (immutable)
- HrResultNotice / HrAcknowledgement
- HrAssessmentObjection
- HrResultRevision
- HrAssessmentArchivePackage
- HrResultApplicationLedger
"""

from django.db import models
from django.utils.translation import gettext_lazy as _

from hr_assessment.models.base import TenantScopedModel


class HrCalibrationSession(TenantScopedModel):
    """校准会话 —— 总册 §86-87。"""
    cycle_id = models.UUIDField(verbose_name=_("所属周期 ID"))
    scope_org_ids_json = models.JSONField(default=list, verbose_name=_("范围组织"))
    classification_profile_json = models.JSONField(default=dict, verbose_name=_("分类 profile"))
    session_status = models.CharField(max_length=30, default="OPEN", verbose_name=_("会话状态"))
    facilitator_staff_id = models.UUIDField(null=True, verbose_name=_("主持人"))
    participants_json = models.JSONField(default=list, verbose_name=_("参与者"))
    opened_at = models.DateTimeField(null=True, verbose_name=_("打开时间"))
    closed_at = models.DateTimeField(null=True, verbose_name=_("关闭时间"))
    policy_version_id = models.UUIDField(null=True, verbose_name=_("政策版本 ID"))

    class Meta:
        db_table = "hr_assessment_calibration_session"
        verbose_name = _("校准会话")


class HrCalibrationRevision(models.Model):
    """校准修订记录 —— 总册 §88。"""
    id = models.UUIDField(primary_key=True)
    session = models.ForeignKey(HrCalibrationSession, on_delete=models.PROTECT, related_name="revisions", verbose_name=_("所属会话"))
    case_id = models.UUIDField(verbose_name=_("Case ID"))
    before_rating_json = models.JSONField(default=dict, verbose_name=_("校准前评分"))
    after_rating_json = models.JSONField(default=dict, verbose_name=_("校准后评分"))
    before_grade_recommendation = models.CharField(max_length=30, default="", verbose_name=_("校准前建议档次"))
    after_grade_recommendation = models.CharField(max_length=30, default="", verbose_name=_("校准后建议档次"))
    reason_code = models.CharField(max_length=50, default="", verbose_name=_("原因码"))
    reason_text = models.TextField(default="", verbose_name=_("原因说明"))
    proposed_by = models.UUIDField(null=True, verbose_name=_("提议人"))
    approved_by = models.UUIDField(null=True, verbose_name=_("批准人"))
    timestamp = models.DateTimeField(auto_now_add=True, verbose_name=_("时间戳"))

    class Meta:
        db_table = "hr_assessment_calibration_revision"


class HrAssessmentDecisionSession(TenantScopedModel):
    """集体审定会话 —— 总册 §90-91。"""
    cycle_id = models.UUIDField(verbose_name=_("所属周期 ID"))
    body_org_id = models.UUIDField(null=True, verbose_name=_("决策机构组织 ID"))
    meeting_at = models.DateTimeField(null=True, verbose_name=_("会议时间"))
    quorum_policy_json = models.JSONField(default=dict, verbose_name=_("法定人数"))
    participants_json = models.JSONField(default=list, verbose_name=_("参与者"))
    agenda_json = models.JSONField(default=dict, verbose_name=_("议程"))
    case_refs_json = models.JSONField(default=list, verbose_name=_("Case 引用"))
    status = models.CharField(max_length=30, default="DRAFT", verbose_name=_("状态"))
    minutes_document_ref = models.UUIDField(null=True, verbose_name=_("纪要文件引用"))
    confidentiality = models.CharField(max_length=30, default="INTERNAL", verbose_name=_("保密级别"))

    class Meta:
        db_table = "hr_assessment_decision_session"
        verbose_name = _("集体审定会话")


class HrFinalAssessmentResult(TenantScopedModel):
    """正式考核结果 —— 总册 §93。FINALIZED 后 immutable。"""
    case_id = models.UUIDField(unique=True, verbose_name=_("考核 Case ID"))
    assessment_type = models.CharField(max_length=30, verbose_name=_("考核类型"))
    cycle_id = models.UUIDField(null=True, verbose_name=_("周期 ID"))
    grade_code = models.CharField(max_length=30, verbose_name=_("档次代码"))
    display_grade_snapshot_json = models.JSONField(default=dict, verbose_name=_("档次显示快照"))
    calculated_score = models.DecimalField(max_digits=10, decimal_places=2, null=True, verbose_name=_("计算分"))
    decision_reason = models.TextField(default="", verbose_name=_("审定理由"))
    policy_version_id = models.UUIDField(null=True, verbose_name=_("政策版本 ID"))
    decision_session_id = models.UUIDField(null=True, verbose_name=_("审定会话 ID"))
    finalized_at = models.DateTimeField(null=True, verbose_name=_("审定时间"))
    finalized_by = models.UUIDField(null=True, verbose_name=_("审定人"))
    result_version_no = models.PositiveSmallIntegerField(default=1, verbose_name=_("结果版本号"))
    content_hash = models.CharField(max_length=64, default="", verbose_name=_("内容哈希"))
    status = models.CharField(max_length=30, default="FINALIZED", db_index=True, verbose_name=_("结果状态"))

    class Meta:
        db_table = "hr_assessment_final_result"
        verbose_name = _("正式考核结果")
        indexes = [
            models.Index(fields=["tenant_id", "assessment_type", "status"]),
            models.Index(fields=["tenant_id", "grade_code", "finalized_at"]),
        ]


class HrResultNotice(TenantScopedModel):
    """结果告知 —— 总册 §95。"""
    result = models.ForeignKey(HrFinalAssessmentResult, on_delete=models.PROTECT, related_name="notices", verbose_name=_("所属结果"))
    notice_no = models.CharField(max_length=50, verbose_name=_("告知编号"))
    result_version = models.PositiveSmallIntegerField(default=1, verbose_name=_("结果版本"))
    generated_document_id = models.UUIDField(null=True, verbose_name=_("生成的文件 ID"))
    delivery_channel = models.CharField(max_length=30, default="SYSTEM", verbose_name=_("送达渠道"))
    delivery_status = models.CharField(max_length=30, default="PENDING", verbose_name=_("送达状态"))
    delivered_at = models.DateTimeField(null=True, verbose_name=_("送达时间"))

    class Meta:
        db_table = "hr_assessment_result_notice"


class HrAcknowledgement(TenantScopedModel):
    """本人意见确认 —— 总册 §96。"""
    result = models.ForeignKey(HrFinalAssessmentResult, on_delete=models.PROTECT, related_name="acknowledgements", verbose_name=_("所属结果"))
    received_at = models.DateTimeField(null=True, verbose_name=_("收到时间"))
    acknowledgement_status = models.CharField(max_length=30, default="NOT_DELIVERED", verbose_name=_("确认状态"))
    employee_opinion = models.TextField(default="", verbose_name=_("本人意见"))
    confirmed_at = models.DateTimeField(null=True, verbose_name=_("确认时间"))

    class Meta:
        db_table = "hr_assessment_acknowledgement"


class HrAssessmentObjection(TenantScopedModel):
    """考核异议/申诉 —— 总册 §97-98。"""
    result = models.ForeignKey(HrFinalAssessmentResult, on_delete=models.PROTECT, related_name="objections", verbose_name=_("所属结果"))
    reason = models.TextField(verbose_name=_("申诉理由"))
    evidence_json = models.JSONField(default=list, verbose_name=_("证据"))
    reviewer_staff_id = models.UUIDField(null=True, verbose_name=_("复核人"))
    conflict_check_json = models.JSONField(default=dict, verbose_name=_("冲突检查"))
    conclusion = models.TextField(default="", verbose_name=_("复核结论"))
    status = models.CharField(max_length=30, default="SUBMITTED", db_index=True, verbose_name=_("处理状态"))
    submitted_at = models.DateTimeField(auto_now_add=True, verbose_name=_("提交时间"))
    resolved_at = models.DateTimeField(null=True, verbose_name=_("解决时间"))

    class Meta:
        db_table = "hr_assessment_objection"


class HrResultRevision(TenantScopedModel):
    """结果修订记录 —— 总册 §99-100。"""
    result = models.ForeignKey(HrFinalAssessmentResult, on_delete=models.PROTECT, related_name="revisions", verbose_name=_("所属结果"))
    previous_version = models.PositiveSmallIntegerField(verbose_name=_("前一版本号"))
    new_version = models.PositiveSmallIntegerField(verbose_name=_("新版本号"))
    revision_type = models.CharField(max_length=30, verbose_name=_("修订类型"))
    reason = models.TextField(verbose_name=_("修订原因"))
    authority_staff_id = models.UUIDField(null=True, verbose_name=_("修订授权人"))
    before_snapshot_json = models.JSONField(default=dict, verbose_name=_("修订前快照"))
    after_snapshot_json = models.JSONField(default=dict, verbose_name=_("修订后快照"))
    effective_at = models.DateTimeField(null=True, verbose_name=_("生效时间"))

    class Meta:
        db_table = "hr_assessment_result_revision"


class HrAssessmentArchivePackage(TenantScopedModel):
    """考核归档包 —— 总册 §101。"""
    result = models.ForeignKey(HrFinalAssessmentResult, on_delete=models.PROTECT, null=True, related_name="archives", verbose_name=_("所属结果"))
    archive_package_id = models.CharField(max_length=100, unique=True, verbose_name=_("归档包 ID"))
    document_refs_json = models.JSONField(default=list, verbose_name=_("文件引用"))
    archive_status = models.CharField(max_length=30, default="PENDING", verbose_name=_("归档状态"))
    archived_at = models.DateTimeField(null=True, verbose_name=_("归档时间"))
    archive_provider_ref = models.CharField(max_length=200, default="", verbose_name=_("归档 Provider 引用"))

    class Meta:
        db_table = "hr_assessment_archive_package"


class HrResultApplicationLedger(TenantScopedModel):
    """结果应用台账 —— 总册 §102。"""
    result = models.ForeignKey(HrFinalAssessmentResult, on_delete=models.PROTECT, related_name="applications", verbose_name=_("所属结果"))
    consumer_domain = models.CharField(max_length=50, verbose_name=_("消费域"))
    consumer_object_id = models.UUIDField(null=True, verbose_name=_("消费对象 ID"))
    purpose = models.CharField(max_length=100, verbose_name=_("用途"))
    result_version = models.PositiveSmallIntegerField(verbose_name=_("消费的版本号"))
    consumed_at = models.DateTimeField(auto_now_add=True, verbose_name=_("消费时间"))
    consumer_status = models.CharField(max_length=30, default="CONSUMED", verbose_name=_("消费状态"))

    class Meta:
        db_table = "hr_assessment_result_application_ledger"
        verbose_name = _("结果应用台账")
        indexes = [models.Index(fields=["consumer_domain", "result_version"])]
