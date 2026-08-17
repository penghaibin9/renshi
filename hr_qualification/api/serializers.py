"""
hr_qualification/api/serializers.py —— API 序列化器。

总册 §107-111：Credential / Rule / Batch / Application / Review / Recognition / Recheck / Risk
"""

from rest_framework import serializers


# ============================================================================
# Credential（总册 §107）
# ============================================================================

class HrCredentialCatalogItemSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    code = serializers.CharField()
    category = serializers.CharField()
    name = serializers.CharField()
    issuer_type = serializers.CharField()
    level_schema = serializers.JSONField(required=False, allow_null=True)
    validity_policy = serializers.JSONField(required=False, allow_null=True)
    requires_document = serializers.BooleanField(default=False)
    requires_external_verification = serializers.BooleanField(default=False)
    status = serializers.CharField(read_only=True)
    version = serializers.IntegerField(read_only=True)


class HrPersonCredentialSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    tenant_id = serializers.IntegerField()
    person_id = serializers.UUIDField()
    staff_master_id = serializers.UUIDField(required=False, allow_null=True)
    external_engagement_id = serializers.IntegerField(required=False, allow_null=True)
    catalog_item_id = serializers.UUIDField()
    catalog_item = HrCredentialCatalogItemSerializer(read_only=True, required=False)
    credential_name_snapshot = serializers.CharField(max_length=200)
    level_code = serializers.CharField(required=False, allow_blank=True, default="")
    masked_no = serializers.CharField(read_only=True)
    certificate_no_cipher = serializers.CharField(required=False, write_only=True)
    issuer_name = serializers.CharField(max_length=200)
    issue_date = serializers.DateField(required=False, allow_null=True)
    valid_from = serializers.DateField(required=False, allow_null=True)
    valid_to = serializers.DateField(required=False, allow_null=True)
    status = serializers.CharField(read_only=True)
    source = serializers.CharField(required=False, default="HR_ENTERED")
    self_reported = serializers.BooleanField(default=False)
    current_verification_status = serializers.CharField(read_only=True)
    last_verified_at = serializers.DateTimeField(read_only=True, allow_null=True)
    version = serializers.IntegerField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)


class HrCredentialCreateSerializer(serializers.Serializer):
    person_id = serializers.UUIDField()
    staff_master_id = serializers.UUIDField(required=False, allow_null=True)
    catalog_item_id = serializers.UUIDField()
    credential_name_snapshot = serializers.CharField(max_length=200)
    level_code = serializers.CharField(required=False, allow_blank=True, default="")
    certificate_no = serializers.CharField(required=False, allow_blank=True, default="")
    issuer_name = serializers.CharField(max_length=200)
    issue_date = serializers.DateField(required=False, allow_null=True)
    valid_from = serializers.DateField(required=False, allow_null=True)
    valid_to = serializers.DateField(required=False, allow_null=True)
    source = serializers.CharField(required=False, default="HR_ENTERED")
    self_reported = serializers.BooleanField(default=False)


class HrCredentialUpdateSerializer(serializers.Serializer):
    credential_name_snapshot = serializers.CharField(max_length=200, required=False)
    level_code = serializers.CharField(required=False, allow_blank=True)
    issuer_name = serializers.CharField(max_length=200, required=False)
    issue_date = serializers.DateField(required=False, allow_null=True)
    valid_from = serializers.DateField(required=False, allow_null=True)
    valid_to = serializers.DateField(required=False, allow_null=True)
    version = serializers.IntegerField()


class HrVerificationSerializer(serializers.Serializer):
    verification_type = serializers.CharField()
    result = serializers.CharField()
    provider = serializers.CharField(required=False, allow_blank=True, default="")
    provider_reference = serializers.CharField(required=False, allow_blank=True, default="")
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class HrCredentialVerificationOutputSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    credential_id = serializers.UUIDField(read_only=True)
    verification_type = serializers.CharField()
    provider = serializers.CharField()
    provider_reference = serializers.CharField()
    result = serializers.CharField()
    verified_by = serializers.IntegerField(allow_null=True)
    verified_at = serializers.DateTimeField(allow_null=True)
    verification_valid_until = serializers.DateTimeField(allow_null=True)
    notes = serializers.CharField()
    created_at = serializers.DateTimeField(read_only=True)


class HrRenewSerializer(serializers.Serializer):
    renewal_type = serializers.CharField(default="SAME_LEVEL")
    reason = serializers.CharField(required=False, allow_blank=True, default="")
    certificate_no = serializers.CharField(required=False, allow_blank=True, default="")
    issuer_name = serializers.CharField(required=False, allow_blank=True, default="")
    issue_date = serializers.DateField(required=False, allow_null=True)
    valid_from = serializers.DateField(required=False, allow_null=True)
    valid_to = serializers.DateField(required=False, allow_null=True)


class HrSuspendRevokeSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, default="")


class HrExactMatchSerializer(serializers.Serializer):
    certificate_no = serializers.CharField()


class HrRequirementMatchOutputSerializer(serializers.Serializer):
    requirement_id = serializers.UUIDField()
    target_type = serializers.CharField()
    target_ref = serializers.CharField()
    credential_category = serializers.CharField()
    result = serializers.CharField()
    matched_credential_id = serializers.UUIDField(allow_null=True)
    detail = serializers.CharField()


# ============================================================================
# Rule Pack（总册 §108）
# ============================================================================

class HrRulePackSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    tenant_id = serializers.IntegerField(allow_null=True)
    jurisdiction_level = serializers.CharField()
    jurisdiction_code = serializers.CharField(required=False, allow_blank=True, default="")
    code = serializers.CharField(max_length=64)
    name = serializers.CharField(max_length=200)
    parent_rule_pack_id = serializers.UUIDField(required=False, allow_null=True)
    status = serializers.CharField(read_only=True)
    version = serializers.IntegerField(read_only=True)


class HrRulePackVersionSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    rule_pack_id = serializers.UUIDField()
    version_no = serializers.IntegerField()
    effective_from = serializers.DateField()
    effective_to = serializers.DateField(required=False, allow_null=True)
    policy_document_ids = serializers.JSONField(required=False, allow_null=True)
    status = serializers.CharField(read_only=True)
    checksum = serializers.CharField(read_only=True)
    published_at = serializers.DateTimeField(read_only=True, allow_null=True)


class HrDoubleTeacherRuleSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    version_id = serializers.UUIDField()
    level = serializers.CharField()
    dimension_code = serializers.CharField()
    rule_code = serializers.CharField(max_length=64)
    rule_type = serializers.CharField()
    operator = serializers.CharField(required=False, allow_blank=True, default=">=")
    expected_value_json = serializers.JSONField(required=False, allow_null=True)
    hard_or_soft = serializers.CharField(default="HARD")
    evidence_type = serializers.CharField(required=False, allow_blank=True, default="")
    source_provider = serializers.CharField(required=False, allow_blank=True, default="")
    manual_review_required = serializers.BooleanField(default=False)
    sequence = serializers.IntegerField(default=0)


# ============================================================================
# Batch + Application（总册 §109）
# ============================================================================

class HrRecognitionBatchSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    tenant_id = serializers.IntegerField()
    batch_no = serializers.CharField(max_length=64)
    name = serializers.CharField(max_length=200)
    school_year = serializers.CharField(required=False, allow_blank=True, default="")
    application_start = serializers.DateField(required=False, allow_null=True)
    application_end = serializers.DateField(required=False, allow_null=True)
    rule_pack_version_id = serializers.UUIDField()
    eligible_scope = serializers.JSONField(required=False, allow_null=True)
    target_levels = serializers.JSONField(required=False, allow_null=True)
    status = serializers.CharField(read_only=True)
    panel_policy_version = serializers.CharField(required=False, allow_blank=True, default="")
    version = serializers.IntegerField(read_only=True)


class HrDoubleTeacherApplicationSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    tenant_id = serializers.IntegerField()
    application_no = serializers.CharField(read_only=True)
    batch_id = serializers.UUIDField()
    person_id = serializers.UUIDField()
    staff_master_id = serializers.UUIDField(required=False, allow_null=True)
    external_engagement_id = serializers.IntegerField(required=False, allow_null=True)
    target_level = serializers.CharField()
    route = serializers.CharField(default="NORMAL")
    status = serializers.CharField(read_only=True)
    submitted_at = serializers.DateTimeField(read_only=True, allow_null=True)
    applicant_statement = serializers.CharField(required=False, allow_blank=True, default="")
    version = serializers.IntegerField(read_only=True)


# ============================================================================
# Review（总册 §110）
# ============================================================================

class HrScoreSheetSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    application_id = serializers.UUIDField()
    panel_member_id = serializers.IntegerField()
    rubric_version_id = serializers.CharField(required=False, allow_blank=True, default="")
    scores_json = serializers.JSONField(required=False, allow_null=True)
    status = serializers.CharField(read_only=True)
    submitted_at = serializers.DateTimeField(read_only=True, allow_null=True)
    version = serializers.IntegerField(read_only=True)


class HrPanelDecisionSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    application_id = serializers.UUIDField()
    panel_id = serializers.UUIDField()
    recommended_level = serializers.CharField(required=False, allow_blank=True, default="")
    decision = serializers.CharField()
    reason_summary = serializers.CharField(required=False, allow_blank=True, default="")
    score_summary = serializers.JSONField(required=False, allow_null=True)
    vote_summary = serializers.JSONField(required=False, allow_null=True)
    finalized_at = serializers.DateTimeField(read_only=True, allow_null=True)


class HrFinalDecisionSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    application_id = serializers.UUIDField()
    decision = serializers.CharField()
    recognized_level = serializers.CharField(required=False, allow_null=True)
    effective_from = serializers.DateField(required=False, allow_null=True)
    effective_to = serializers.DateField(required=False, allow_null=True)
    decision_authority = serializers.CharField(required=False, allow_blank=True, default="")
    meeting_ref = serializers.CharField(required=False, allow_blank=True, default="")
    published_at = serializers.DateTimeField(read_only=True, allow_null=True)
    version = serializers.IntegerField(read_only=True)


# ============================================================================
# Recognition / Recheck / Risk（总册 §111）
# ============================================================================

class HrDoubleTeacherRecognitionSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    tenant_id = serializers.IntegerField()
    person_id = serializers.UUIDField()
    staff_master_id = serializers.UUIDField(allow_null=True, required=False)
    recognition_no = serializers.CharField(read_only=True)
    level = serializers.CharField()
    rule_pack_version_id = serializers.UUIDField()
    batch_id = serializers.UUIDField(allow_null=True, required=False)
    application_id = serializers.UUIDField(allow_null=True, required=False)
    effective_from = serializers.DateField()
    effective_to = serializers.DateField(allow_null=True, required=False)
    review_due_at = serializers.DateField(allow_null=True, required=False)
    status = serializers.CharField(read_only=True)
    recognition_authority = serializers.CharField(required=False, allow_blank=True, default="")
    version = serializers.IntegerField(read_only=True)


class HrRecheckCaseSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    recognition_id = serializers.UUIDField()
    trigger = serializers.CharField()
    due_at = serializers.DateField(required=False, allow_null=True)
    rule_version = serializers.CharField(required=False, allow_blank=True, default="")
    status = serializers.CharField(read_only=True)
    evidence_snapshot = serializers.JSONField(required=False, allow_null=True)
    decision = serializers.CharField(required=False, allow_null=True)
    decided_at = serializers.DateTimeField(read_only=True, allow_null=True)


class HrRecheckDecisionSerializer(serializers.Serializer):
    decision = serializers.CharField()


class HrQualificationRiskSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    tenant_id = serializers.IntegerField()
    person_id = serializers.UUIDField()
    credential_id = serializers.UUIDField(required=False, allow_null=True)
    recognition_id = serializers.UUIDField(required=False, allow_null=True)
    risk_type = serializers.CharField()
    severity = serializers.CharField(default="MEDIUM")
    opened_at = serializers.DateTimeField(read_only=True)
    owner = serializers.CharField(required=False, allow_blank=True, default="")
    due_at = serializers.DateField(required=False, allow_null=True)
    status = serializers.CharField(read_only=True)
    resolution = serializers.CharField(read_only=True)
    resolved_at = serializers.DateTimeField(read_only=True, allow_null=True)


class HrRiskResolveSerializer(serializers.Serializer):
    resolution = serializers.CharField()


# ============================================================================
# API Envelope（总册 §106）
# ============================================================================

def envelope(data, request_id=None):
    import uuid as _uuid
    return {
        "apiVersion": "v1",
        "schemaVersion": "hr09.1",
        "requestId": request_id or str(_uuid.uuid4()),
        "data": data,
    }


def error_envelope(code, message, details=None, request_id=None, retryable=False):
    import uuid as _uuid
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
            "retryable": retryable,
        },
        "requestId": request_id or str(_uuid.uuid4()),
    }
