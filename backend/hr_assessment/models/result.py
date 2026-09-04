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

import hashlib
import json
import uuid

from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from hr_assessment.models.base import TenantManager, TenantScopedModel


def default_correction_no() -> str:
    """Return a collision-resistant public idempotency key for old callers."""

    return f"COR-{uuid.uuid4().hex.upper()}"


def _canonical_hash(payload: dict) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class _AppendOnlyResultQuerySet(models.QuerySet):
    immutable_code = "HR12_RESULT_FACT_IMMUTABLE"

    def update(self, **kwargs):
        raise ValueError(f"{self.immutable_code}: append a correction fact")

    def delete(self):
        raise ValueError(f"{self.immutable_code}: formal facts cannot be deleted")

    def bulk_update(self, objs, fields, batch_size=None):
        raise ValueError(f"{self.immutable_code}: append a correction fact")


class _AppendOnlyResultManager(TenantManager.from_queryset(_AppendOnlyResultQuerySet)):
    def bulk_create(self, objs, *args, **kwargs):
        for obj in objs:
            validate_chain = getattr(obj, "_validate_chain", None)
            if validate_chain is not None:
                validate_chain()
            obj._prepare_seal()
        return super().bulk_create(objs, *args, **kwargs)


class _AppendOnlyLedgerQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValueError("HR12_RESULT_APPLICATION_LEDGER_IMMUTABLE")

    def delete(self):
        raise ValueError("HR12_RESULT_APPLICATION_LEDGER_IMMUTABLE")

    def bulk_update(self, objs, fields, batch_size=None):
        raise ValueError("HR12_RESULT_APPLICATION_LEDGER_IMMUTABLE")


class _AppendOnlyLedgerManager(
    TenantManager.from_queryset(_AppendOnlyLedgerQuerySet)
):
    def bulk_create(self, objs, *args, **kwargs):
        for obj in objs:
            obj._validate_scope()
        return super().bulk_create(objs, *args, **kwargs)


class _CompletedDecisionQuerySet(models.QuerySet):
    immutable_code = "HR12_COMPLETED_DECISION_IMMUTABLE"

    def update(self, **kwargs):
        if (
            str(kwargs.get("status") or "").upper() == "COMPLETED"
            or self.filter(status="COMPLETED").exists()
        ):
            raise ValueError(self.immutable_code)
        return super().update(**kwargs)

    def delete(self):
        if self.filter(status="COMPLETED").exists():
            raise ValueError(self.immutable_code)
        return super().delete()

    def bulk_update(self, objs, fields, batch_size=None):
        raise ValueError(self.immutable_code)


class _CompletedDecisionManager(
    TenantManager.from_queryset(_CompletedDecisionQuerySet)
):
    pass


class _AppendOnlyDocumentQuerySet(models.QuerySet):
    immutable_code = "HR12_SEALED_DOCUMENT_IMMUTABLE"

    def update(self, **kwargs):
        raise ValueError(self.immutable_code)

    def delete(self):
        raise ValueError(self.immutable_code)

    def bulk_update(self, objs, fields, batch_size=None):
        raise ValueError(self.immutable_code)


class _AppendOnlyDocumentManager(
    TenantManager.from_queryset(_AppendOnlyDocumentQuerySet)
):
    def bulk_create(self, objs, *args, **kwargs):
        raise ValueError("HR12_SEALED_DOCUMENT_SERVICE_REQUIRED")


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
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
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
    body_org_id = models.BigIntegerField(null=True, verbose_name=_("HR02 决策机构组织 ID"))
    meeting_at = models.DateTimeField(null=True, verbose_name=_("会议时间"))
    quorum_policy_json = models.JSONField(default=dict, verbose_name=_("法定人数"))
    participants_json = models.JSONField(default=list, verbose_name=_("参与者"))
    agenda_json = models.JSONField(default=dict, verbose_name=_("议程"))
    case_refs_json = models.JSONField(default=list, verbose_name=_("Case 引用"))
    status = models.CharField(max_length=30, default="DRAFT", verbose_name=_("状态"))
    minutes_document_ref = models.UUIDField(null=True, verbose_name=_("纪要文件引用"))
    confidentiality = models.CharField(max_length=30, default="INTERNAL", verbose_name=_("保密级别"))

    objects = _CompletedDecisionManager()

    def save(self, *args, **kwargs) -> None:
        if not self._state.adding:
            old = type(self).objects.filter(pk=self.pk).only("status").first()
            if old is not None and old.status == "COMPLETED":
                raise ValueError("HR12_COMPLETED_DECISION_IMMUTABLE")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.status == "COMPLETED":
            raise ValueError("HR12_COMPLETED_DECISION_IMMUTABLE")
        return super().delete(*args, **kwargs)

    class Meta:
        db_table = "hr_assessment_decision_session"
        verbose_name = _("集体审定会话")


class HrAssessmentDocument(TenantScopedModel):
    """HR12 受控业务文件元数据；文件正文只保存于 protected 存储。"""

    document_type = models.CharField(max_length=40, verbose_name=_("文件类型"))
    related_object_type = models.CharField(max_length=40, verbose_name=_("关联对象类型"))
    related_object_id = models.UUIDField(db_index=True, verbose_name=_("关联对象 ID"))
    storage_key = models.CharField(max_length=512, verbose_name=_("受控存储键"))
    original_filename = models.CharField(max_length=255, verbose_name=_("原始文件名"))
    content_type = models.CharField(max_length=127, default="", verbose_name=_("内容类型"))
    size_bytes = models.PositiveBigIntegerField(verbose_name=_("文件字节数"))
    sha256 = models.CharField(max_length=64, verbose_name=_("SHA-256"))
    uploaded_by = models.BigIntegerField(null=True, verbose_name=_("上传账号"))
    sealed_at = models.DateTimeField(verbose_name=_("封存时间"))
    status = models.CharField(max_length=20, default="SEALED", verbose_name=_("状态"))

    objects = _AppendOnlyDocumentManager()

    def save(self, *args, **kwargs) -> None:
        if not self._state.adding:
            raise ValueError("HR12_SEALED_DOCUMENT_IMMUTABLE")
        if (
            self.status != "SEALED"
            or not self.sealed_at
            or not self.storage_key
            or len(str(self.sha256 or "")) != 64
            or int(self.size_bytes or 0) <= 0
        ):
            raise ValueError("HR12_SEALED_DOCUMENT_INVALID")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("HR12_SEALED_DOCUMENT_IMMUTABLE")

    class Meta:
        db_table = "hr_assessment_document"
        verbose_name = _("考核受控文件")
        constraints = [
            models.UniqueConstraint(
                fields=(
                    "tenant_id",
                    "document_type",
                    "related_object_type",
                    "related_object_id",
                ),
                name="hr12_document_business_object_uq",
            )
        ]


class _AppendOnlyDocumentAccessAuditQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValueError("HR12_DOCUMENT_ACCESS_AUDIT_IMMUTABLE")

    def delete(self):
        raise ValueError("HR12_DOCUMENT_ACCESS_AUDIT_IMMUTABLE")


class HrAssessmentDocumentAccessAudit(TenantScopedModel):
    """Append-only receipt for each successful confidential document download."""

    document = models.ForeignKey(
        HrAssessmentDocument,
        on_delete=models.PROTECT,
        related_name="access_audits",
    )
    actor_user_id = models.PositiveBigIntegerField()
    purpose = models.CharField(max_length=500)
    request_id = models.CharField(max_length=128, blank=True, default="")

    objects = _AppendOnlyDocumentAccessAuditQuerySet.as_manager()

    class Meta:
        db_table = "hr12_document_access_audit"
        indexes = [
            models.Index(
                fields=("tenant_id", "document", "created_at"),
                name="idx_hr12_doc_access",
            ),
            models.Index(
                fields=("tenant_id", "actor_user_id", "created_at"),
                name="idx_hr12_doc_actor_access",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(purpose__gt=""),
                name="ck_hr12_doc_access_purpose",
            )
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValueError("HR12_DOCUMENT_ACCESS_AUDIT_IMMUTABLE")
        if not str(self.purpose or "").strip():
            raise ValueError("HR12_DOCUMENT_ACCESS_REASON_REQUIRED")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("HR12_DOCUMENT_ACCESS_AUDIT_IMMUTABLE")


class HrFinalAssessmentResult(TenantScopedModel):
    """正式考核结果 —— 总册 §93。FINALIZED 后 immutable。"""
    case_id = models.UUIDField(unique=True, verbose_name=_("考核 Case ID"))
    assessment_type = models.CharField(max_length=30, verbose_name=_("考核类型"))
    cycle_id = models.UUIDField(null=True, verbose_name=_("周期 ID"))
    grade_code = models.CharField(max_length=30, verbose_name=_("档次代码"))
    display_grade_snapshot_json = models.JSONField(default=dict, verbose_name=_("档次显示快照"))
    calculated_score = models.DecimalField(max_digits=10, decimal_places=2, null=True, verbose_name=_("计算分"))
    calculation_snapshot_json = models.JSONField(
        default=dict,
        verbose_name=_("服务端计算依据快照"),
    )
    calculation_hash = models.CharField(
        max_length=64,
        default="",
        verbose_name=_("计算依据哈希"),
    )
    decision_reason = models.TextField(default="", verbose_name=_("审定理由"))
    policy_version_id = models.UUIDField(null=True, verbose_name=_("政策版本 ID"))
    decision_session_id = models.UUIDField(null=True, verbose_name=_("审定会话 ID"))
    finalized_at = models.DateTimeField(null=True, verbose_name=_("审定时间"))
    finalized_by = models.UUIDField(null=True, verbose_name=_("审定人"))
    result_version_no = models.PositiveSmallIntegerField(default=1, verbose_name=_("结果版本号"))
    content_hash = models.CharField(max_length=64, default="", verbose_name=_("内容哈希"))
    sealed_at = models.DateTimeField(null=False, verbose_name=_("封板时间"))
    status = models.CharField(max_length=30, default="FINALIZED", db_index=True, verbose_name=_("结果状态"))

    objects = _AppendOnlyResultManager()

    def canonical_payload(self) -> dict:
        return {
            "tenantId": int(self.tenant_id),
            "caseId": str(self.case_id),
            "assessmentType": self.assessment_type,
            "cycleId": str(self.cycle_id) if self.cycle_id else None,
            "gradeCode": self.grade_code,
            "displayGrade": self.display_grade_snapshot_json or {},
            "calculatedScore": (
                str(self.calculated_score) if self.calculated_score is not None else None
            ),
            "decisionReason": self.decision_reason or "",
            "policyVersionId": (
                str(self.policy_version_id) if self.policy_version_id else None
            ),
            "decisionSessionId": (
                str(self.decision_session_id) if self.decision_session_id else None
            ),
            "finalizedAt": self.finalized_at.isoformat() if self.finalized_at else None,
            "finalizedBy": str(self.finalized_by) if self.finalized_by else None,
            "resultVersionNo": int(self.result_version_no),
            "status": self.status,
        }

    def calculate_content_hash(self) -> str:
        return _canonical_hash(self.canonical_payload())

    def calculate_calculation_hash(self) -> str:
        return _canonical_hash(self.calculation_snapshot_json or {})

    def _prepare_seal(self) -> None:
        if not self.finalized_at:
            self.finalized_at = timezone.now()
        if not self.sealed_at:
            self.sealed_at = self.finalized_at
        expected = self.calculate_content_hash()
        if self.content_hash and self.content_hash != expected:
            raise ValueError("HR12_RESULT_CONTENT_HASH_MISMATCH")
        self.content_hash = expected
        calculation_hash = self.calculate_calculation_hash()
        if self.calculation_hash and self.calculation_hash != calculation_hash:
            raise ValueError("HR12_RESULT_CALCULATION_HASH_MISMATCH")
        self.calculation_hash = calculation_hash

    def save(self, *args, **kwargs) -> None:
        if not self._state.adding:
            raise ValueError(
                "HR12_FINAL_RESULT_IMMUTABLE: append HrResultRevision instead"
            )
        self._prepare_seal()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("HR12_FINAL_RESULT_IMMUTABLE: formal result cannot be deleted")

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
    delivery_receipt_ref = models.CharField(
        max_length=200,
        default="",
        verbose_name=_("送达回执引用"),
    )
    delivered_at = models.DateTimeField(null=True, verbose_name=_("送达时间"))

    class Meta:
        db_table = "hr_assessment_result_notice"
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "notice_no"),
                name="hr12_notice_tenant_no_uq",
            ),
            models.UniqueConstraint(
                fields=("tenant_id", "result", "result_version"),
                name="hr12_notice_result_version_uq",
            ),
        ]


class HrAcknowledgement(TenantScopedModel):
    """本人意见确认 —— 总册 §96。"""
    result = models.ForeignKey(HrFinalAssessmentResult, on_delete=models.PROTECT, related_name="acknowledgements", verbose_name=_("所属结果"))
    result_version = models.PositiveSmallIntegerField(default=1, verbose_name=_("结果版本"))
    received_at = models.DateTimeField(null=True, verbose_name=_("收到时间"))
    acknowledgement_status = models.CharField(max_length=30, default="NOT_DELIVERED", verbose_name=_("确认状态"))
    employee_opinion = models.TextField(default="", verbose_name=_("本人意见"))
    confirmed_at = models.DateTimeField(null=True, verbose_name=_("确认时间"))

    class Meta:
        db_table = "hr_assessment_acknowledgement"
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "result", "result_version"),
                name="hr12_ack_result_version_uq",
            )
        ]


class HrAssessmentObjection(TenantScopedModel):
    """考核异议/申诉 —— 总册 §97-98。"""
    result = models.ForeignKey(HrFinalAssessmentResult, on_delete=models.PROTECT, related_name="objections", verbose_name=_("所属结果"))
    result_version = models.PositiveSmallIntegerField(default=1, verbose_name=_("异议对应结果版本"))
    submitted_by_staff_id = models.UUIDField(null=True, verbose_name=_("异议提交人"))
    reason = models.TextField(verbose_name=_("申诉理由"))
    evidence_json = models.JSONField(default=list, verbose_name=_("证据"))
    reviewer_staff_id = models.UUIDField(null=True, verbose_name=_("复核人"))
    conflict_check_json = models.JSONField(default=dict, verbose_name=_("冲突检查"))
    conclusion = models.TextField(default="", verbose_name=_("复核结论"))
    decision_code = models.CharField(max_length=30, default="", verbose_name=_("复核决定"))
    resolution_revision_id = models.UUIDField(null=True, verbose_name=_("结果更正版本 ID"))
    status = models.CharField(max_length=30, default="SUBMITTED", db_index=True, verbose_name=_("处理状态"))
    submitted_at = models.DateTimeField(auto_now_add=True, verbose_name=_("提交时间"))
    resolved_at = models.DateTimeField(null=True, verbose_name=_("解决时间"))

    class Meta:
        db_table = "hr_assessment_objection"
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "result", "result_version"),
                name="hr12_objection_result_version_uq",
            )
        ]


class HrResultRevision(TenantScopedModel):
    """结果修订记录 —— 总册 §99-100。"""
    result = models.ForeignKey(HrFinalAssessmentResult, on_delete=models.PROTECT, related_name="revisions", verbose_name=_("所属结果"))
    correction_no = models.CharField(
        max_length=80,
        default=default_correction_no,
        verbose_name=_("更正幂等编号"),
    )
    previous_version = models.PositiveSmallIntegerField(verbose_name=_("前一版本号"))
    new_version = models.PositiveSmallIntegerField(verbose_name=_("新版本号"))
    revision_type = models.CharField(max_length=30, verbose_name=_("修订类型"))
    reason = models.TextField(verbose_name=_("修订原因"))
    authority_staff_id = models.UUIDField(null=True, verbose_name=_("修订授权人"))
    before_snapshot_json = models.JSONField(default=dict, verbose_name=_("修订前快照"))
    after_snapshot_json = models.JSONField(default=dict, verbose_name=_("修订后快照"))
    effective_at = models.DateTimeField(null=True, verbose_name=_("生效时间"))
    content_hash = models.CharField(max_length=64, default="", verbose_name=_("内容哈希"))
    sealed_at = models.DateTimeField(null=False, verbose_name=_("封板时间"))

    objects = _AppendOnlyResultManager()

    def canonical_payload(self) -> dict:
        return {
            "tenantId": int(self.tenant_id),
            "resultId": str(self.result_id),
            "correctionNo": self.correction_no,
            "previousVersion": int(self.previous_version),
            "newVersion": int(self.new_version),
            "revisionType": self.revision_type,
            "reason": self.reason,
            "authorityStaffId": (
                str(self.authority_staff_id) if self.authority_staff_id else None
            ),
            "before": self.before_snapshot_json or {},
            "after": self.after_snapshot_json or {},
            "effectiveAt": self.effective_at.isoformat() if self.effective_at else None,
        }

    def calculate_content_hash(self) -> str:
        return _canonical_hash(self.canonical_payload())

    @staticmethod
    def _base_snapshot(result: HrFinalAssessmentResult) -> dict:
        return {
            "sourceResultId": str(result.id),
            "sourceContentHash": result.content_hash,
            "version": int(result.result_version_no),
            "status": result.status,
            "gradeCode": result.grade_code,
            "displayGrade": result.display_grade_snapshot_json or {},
            "calculatedScore": (
                str(result.calculated_score)
                if result.calculated_score is not None
                else None
            ),
            "decisionReason": result.decision_reason or "",
        }

    def _validate_chain(self) -> None:
        if not self.result_id:
            raise ValueError("HR12_RESULT_REVISION_RESULT_REQUIRED")
        result = self.result
        if int(result.tenant_id) != int(self.tenant_id):
            raise ValueError("HR12_RESULT_REVISION_SCOPE_MISMATCH")
        if int(self.new_version) != int(self.previous_version) + 1:
            raise ValueError("HR12_RESULT_REVISION_VERSION_INVALID")
        latest = (
            HrResultRevision.objects.filter(
                tenant_id=self.tenant_id,
                result_id=self.result_id,
            )
            .order_by("-new_version", "-effective_at", "-id")
            .first()
        )
        expected_before = (
            latest.after_snapshot_json or {}
            if latest is not None
            else self._base_snapshot(result)
        )
        current_version = (
            int(latest.new_version)
            if latest is not None
            else int(result.result_version_no)
        )
        if int(self.previous_version) != current_version:
            raise ValueError("HR12_RESULT_REVISION_VERSION_CONFLICT")
        if (self.before_snapshot_json or {}) != expected_before:
            raise ValueError("HR12_RESULT_REVISION_BEFORE_SNAPSHOT_MISMATCH")
        after = self.after_snapshot_json or {}
        if int(after.get("version") or 0) != int(self.new_version):
            raise ValueError("HR12_RESULT_REVISION_AFTER_SNAPSHOT_INVALID")

    def _prepare_seal(self) -> None:
        if not self.effective_at:
            self.effective_at = timezone.now()
        if not self.sealed_at:
            self.sealed_at = self.effective_at
        expected = self.calculate_content_hash()
        if self.content_hash and self.content_hash != expected:
            raise ValueError("HR12_RESULT_REVISION_CONTENT_HASH_MISMATCH")
        self.content_hash = expected

    def save(self, *args, **kwargs) -> None:
        if not self._state.adding:
            raise ValueError(
                "HR12_RESULT_REVISION_IMMUTABLE: append another correction fact"
            )
        self._validate_chain()
        self._prepare_seal()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError(
            "HR12_RESULT_REVISION_IMMUTABLE: correction history cannot be deleted"
        )

    class Meta:
        db_table = "hr_assessment_result_revision"
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "correction_no"),
                name="hr12_revision_tenant_correction_uq",
            ),
            models.UniqueConstraint(
                fields=("result", "new_version"),
                name="hr12_revision_result_version_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(new_version__gt=models.F("previous_version")),
                name="hr12_revision_version_forward_ck",
            ),
        ]


class HrAssessmentArchivePackage(TenantScopedModel):
    """考核归档包 —— 总册 §101。"""
    result = models.ForeignKey(HrFinalAssessmentResult, on_delete=models.PROTECT, null=True, related_name="archives", verbose_name=_("所属结果"))
    archive_package_id = models.CharField(max_length=100, unique=True, verbose_name=_("归档包 ID"))
    result_version = models.PositiveSmallIntegerField(default=1, verbose_name=_("结果版本"))
    document_refs_json = models.JSONField(default=list, verbose_name=_("文件引用"))
    manifest_json = models.JSONField(default=dict, verbose_name=_("归档清单"))
    content_hash = models.CharField(max_length=64, default="", verbose_name=_("归档内容哈希"))
    archive_status = models.CharField(max_length=30, default="PENDING", verbose_name=_("归档状态"))
    archived_at = models.DateTimeField(null=True, verbose_name=_("归档时间"))
    sealed_at = models.DateTimeField(null=True, verbose_name=_("封存时间"))
    archive_provider_ref = models.CharField(max_length=200, default="", verbose_name=_("归档 Provider 引用"))

    class Meta:
        db_table = "hr_assessment_archive_package"
        constraints = [
            models.UniqueConstraint(
                fields=("tenant_id", "result", "result_version"),
                name="hr12_archive_result_version_uq",
            )
        ]


class HrResultApplicationLedger(TenantScopedModel):
    """结果应用台账 —— 总册 §102。"""
    result = models.ForeignKey(HrFinalAssessmentResult, on_delete=models.PROTECT, related_name="applications", verbose_name=_("所属结果"))
    consumer_domain = models.CharField(max_length=50, verbose_name=_("消费域"))
    consumer_object_id = models.UUIDField(null=True, verbose_name=_("消费对象 ID"))
    purpose = models.CharField(max_length=100, verbose_name=_("用途"))
    result_version = models.PositiveSmallIntegerField(verbose_name=_("消费的版本号"))
    consumed_at = models.DateTimeField(auto_now_add=True, verbose_name=_("消费时间"))
    consumer_status = models.CharField(max_length=30, default="CONSUMED", verbose_name=_("消费状态"))

    objects = _AppendOnlyLedgerManager()

    def _validate_scope(self) -> None:
        if not self.result_id:
            raise ValueError("HR12_RESULT_APPLICATION_LEDGER_RESULT_REQUIRED")
        if int(self.result.tenant_id) != int(self.tenant_id):
            raise ValueError("HR12_RESULT_APPLICATION_LEDGER_SCOPE_MISMATCH")
        if (
            self.consumer_object_id is None
            or not str(self.consumer_domain or "").strip()
            or not str(self.purpose or "").strip()
            or int(self.result_version or 0) < 1
        ):
            raise ValueError("HR12_RESULT_APPLICATION_LEDGER_INVALID")

    def save(self, *args, **kwargs) -> None:
        if not self._state.adding:
            raise ValueError("HR12_RESULT_APPLICATION_LEDGER_IMMUTABLE")
        self._validate_scope()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("HR12_RESULT_APPLICATION_LEDGER_IMMUTABLE")

    class Meta:
        db_table = "hr_assessment_result_application_ledger"
        verbose_name = _("结果应用台账")
        indexes = [models.Index(fields=["consumer_domain", "result_version"])]
        constraints = [
            models.UniqueConstraint(
                fields=(
                    "tenant_id",
                    "result",
                    "consumer_domain",
                    "consumer_object_id",
                    "purpose",
                    "result_version",
                ),
                name="hr12_result_application_idempotency_uq",
            )
        ]
