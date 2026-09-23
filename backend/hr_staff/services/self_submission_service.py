"""SELF-safe entry points into HR03's existing correction/material authorities.

Submission is not application. Only the HR03 independent approval/apply chain
can change a formal dossier. New documents are UNVERIFIED until HR accepts.
"""
import hashlib
import json
import re
from datetime import date
from types import SimpleNamespace
from django.db import transaction
from django.db.models import Max
from django.utils import timezone
from hr_staff.constants import CorrectionEditMode, CorrectionStatus
from hr_staff.models import (HrCorrectionCase, HrFieldGovernancePolicy, HrStaffMaster,
    HrPersonContact, HrStaffMaterialVersion, HrMaterialRequest, HrMaterialSubmission)
from hr_staff.policies import get_field_policy
from hr_staff.services.audit_service import write_audit_event
from hr_staff.services.correction_service import CorrectionService, CorrectionPolicyDenied, CorrectionStateError
from hr_staff.services.correction_fields import get_correction_field_handler
from hr_self.command_contract import SELF_FIELDS, CommandError, check_object, expected_version


def assert_independent_reviewer(tenant, actor, staff_id, submitted_by):
    from django.contrib.auth import get_user_model
    from hr_self.services.identity_service import SelfIdentityService, SelfIdentityError
    if actor is None or actor == submitted_by:
        raise CorrectionPolicyDenied("SELF_APPROVAL_FORBIDDEN: 不得审核本人提交的事项")
    user = get_user_model().objects.filter(pk=actor).first()
    if user is None or not user.is_active:
        raise CorrectionPolicyDenied("REVIEWER_INACTIVE")
    try:
        identity = SelfIdentityService(tenant).resolve(user)
    except SelfIdentityError as exc:
        if exc.code == "SELF_IDENTITY_AMBIGUOUS":
            raise CorrectionPolicyDenied("REVIEWER_IDENTITY_AMBIGUOUS") from exc
        identity = None
    if identity and str(identity.staff_id) == str(staff_id):
        raise CorrectionPolicyDenied("SELF_APPROVAL_FORBIDDEN: 不得审核本人人事档案")


def _current_values(staff, fields):
    result = {}
    for field in sorted(fields):
        if field.startswith("person."):
            value = getattr(staff.person_id, field.split(".")[1])
            result[field] = value.isoformat() if isinstance(value, date) else value
        else:
            kind = {"contact.mobile": "PERSONAL_MOBILE", "contact.personal_email": "PERSONAL_EMAIL"}[field]
            rows = list(HrPersonContact.objects.filter(tenant_id=staff.tenant_id,
                person_id=staff.person_id_id, contact_kind=kind).order_by("id")[:2])
            if len(rows) > 1:
                raise CorrectionPolicyDenied("CONTACT_AMBIGUOUS: 联系方式存在重复主记录，须先治理")
            result[field] = rows[0].contact_value if rows else ""
    return result


def _source_hash(staff, fields):
    return hashlib.sha256(json.dumps(_current_values(staff, fields), sort_keys=True,
        ensure_ascii=False, default=str).encode()).hexdigest()


def verify_correction_source(case):
    # Serialize SELF application with other supported edits to the same staff.
    staff = HrStaffMaster.objects.select_for_update().select_related("person_id").get(
        tenant_id=case.tenant_id, pk=case.staff_id_id)
    from hr_staff.services.evidence_reference_service import evidence_snapshot
    if not case.source_evidence_version_id:
        raise CorrectionPolicyDenied("SELF_EVIDENCE_VERSION_REQUIRED")
    evidence_snapshot(case.tenant_id, case.staff_id_id, case.source_evidence_version_id, lock=True)
    fields = list(case.items.values_list("field_code", flat=True))
    if not fields or set(fields) - SELF_FIELDS.keys():
        raise CorrectionPolicyDenied("SELF_FIELD_NOT_ALLOWED")
    if case.source_snapshot_hash != _source_hash(staff, fields):
        raise CorrectionStateError("SELF_SOURCE_CHANGED: 申请后档案已有变动，请重新提交，不覆盖新数据")
    for field in fields:
        policy = HrFieldGovernancePolicy.objects.filter(tenant_id=case.tenant_id, field_code=field).first()
        if policy and (not policy.is_enabled or policy.edit_mode == CorrectionEditMode.BUSINESS_PROCESS_ONLY):
            raise CorrectionPolicyDenied("SELF_POLICY_CHANGED")


class SelfCorrectionService:
    def __init__(self, context):
        self.context = context
        self.tenant, self.staff_id, self.actor = context.tenant_id, context.staff_id, context.user_id
        self.authority = CorrectionService(self.tenant, self.actor)

    @transaction.atomic
    def create_and_submit(self, *, reason, items, evidence_version_id):
        from hr_staff.services.evidence_reference_service import evidence_snapshot
        if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 512:
            raise CommandError("REASON_REQUIRED", "请填写512字以内的更正原因")
        if not isinstance(items, list) or not 1 <= len(items) <= 5:
            raise CommandError("ITEMS_INVALID", "每次提交1至5项更正")
        staff = HrStaffMaster.objects.select_for_update().select_related("person_id").get(
            tenant_id=self.tenant, pk=self.staff_id)
        evidence_snapshot(self.tenant, self.staff_id, evidence_version_id, lock=True)
        evidence = HrStaffMaterialVersion.objects.get(tenant_id=self.tenant, pk=evidence_version_id)
        clean, seen = [], set()
        for item in items:
            check_object(item, {"fieldCode", "newValue"})
            code = item.get("fieldCode")
            if code not in SELF_FIELDS or code in seen:
                raise CommandError("SELF_FIELD_NOT_ALLOWED", "字段未开放或重复；职务、工资、合同、工号不能自助更改")
            seen.add(code)
            policy = HrFieldGovernancePolicy.objects.filter(tenant_id=self.tenant, field_code=code).first()
            if policy and not policy.is_enabled:
                raise CorrectionPolicyDenied("FIELD_DISABLED")
            policy = policy or get_field_policy(code)
            if not policy or policy.edit_mode == CorrectionEditMode.BUSINESS_PROCESS_ONLY:
                raise CorrectionPolicyDenied("SELF_FIELD_NOT_ALLOWED")
            value = item.get("newValue")
            if not isinstance(value, str) or not value.strip() or len(value) > 200:
                raise CommandError("NEW_VALUE_INVALID", "更正值须为200字以内有效文本")
            value = value.strip()
            if code == "contact.mobile" and not re.fullmatch(r"[+0-9() -]{6,32}", value):
                raise CommandError("PHONE_INVALID", "联系电话格式无效")
            get_correction_field_handler(code).validator(value, SimpleNamespace(field_code=code))
            clean.append({"field_code": code, "fact_type": code.split(".")[0],
                "new_value_masked": value, "effective_date": timezone.localdate()})
        case = self.authority.create_case(staff_id=staff, reason=reason.strip(), items=clean,
            evidence_material_id=evidence.material_id_id)
        case.source_channel, case.source_snapshot_hash = "SELF", _source_hash(staff, seen)
        case.source_evidence_version_id = evidence.id
        case.save(update_fields=["source_channel", "source_snapshot_hash", "source_evidence_version_id"])
        return self.authority.submit(case.id)

    @transaction.atomic
    def act(self, case_id, *, action, version, evidence_version_id=None):
        from hr_staff.services.evidence_reference_service import evidence_snapshot
        case = HrCorrectionCase.objects.select_for_update().filter(tenant_id=self.tenant,
            pk=case_id, staff_id=self.staff_id, source_channel="SELF").first()
        if case is None:
            raise CommandError("NOT_FOUND", "未找到本人事项", 404)
        if case.version != expected_version(version):
            raise CommandError("VERSION_CONFLICT", "事项已变化，请刷新后重试", 409)
        if action == "CANCEL":
            return self.authority.cancel(case.id)
        if action != "RESUBMIT" or case.status != CorrectionStatus.RETURNED:
            raise CommandError("STATE_CONFLICT", "只有退回申请可以补件重交", 409)
        snapshot = evidence_snapshot(self.tenant, self.staff_id, evidence_version_id, lock=True)
        old_id = case.evidence_material_id
        case.evidence_material_id = snapshot["materialId"]
        case.source_evidence_version_id = evidence_version_id
        case.save(update_fields=["evidence_material_id", "source_evidence_version_id"])
        write_audit_event(tenant_id=self.tenant, action="SelfCorrectionEvidenceSupplemented",
            actor_user_id=self.actor, staff_id=self.staff_id, business_type="CORRECTION",
            business_id=str(case.id), reason=json.dumps({"oldMaterialId": str(old_id), "newEvidence": snapshot}))
        return self.authority.resubmit(case.id)


class MaterialSubmissionService:
    def __init__(self, tenant, actor):
        self.tenant, self.actor = tenant, actor

    @transaction.atomic
    def submit(self, *, request_id, staff_id, material_version_id):
        from hr_staff.services.evidence_reference_service import evidence_snapshot
        request = HrMaterialRequest.objects.select_for_update().filter(tenant_id=self.tenant,
            pk=request_id, target_staff_id=staff_id).first()
        if not request:
            raise CommandError("NOT_FOUND", "未找到本人的补件要求", 404)
        if request.status != "REQUESTED":
            raise CommandError("STATE_CONFLICT", "该补件要求当前不允许再次提交", 409)
        snapshot = evidence_snapshot(self.tenant, staff_id, material_version_id, lock=True)
        version = HrStaffMaterialVersion.objects.select_related("material_id").get(
            tenant_id=self.tenant, pk=material_version_id)
        if request.required_category_code and version.material_id.category_code != request.required_category_code:
            raise CommandError("CATEGORY_MISMATCH", "上传材料分类与补件要求不一致")
        revision = (HrMaterialSubmission.objects.filter(tenant_id=self.tenant, request=request)
            .aggregate(n=Max("revision"))["n"] or 0) + 1
        item = HrMaterialSubmission.objects.create(tenant_id=self.tenant, request=request,
            material_version=version, revision=revision, submitted_by=self.actor,
            evidence_hash=snapshot["sha256"])
        request.status = "SUBMITTED"
        request.save(update_fields=["status", "updated_at"])
        self._audit(item, staff_id, "SelfMaterialSubmitted")
        return item

    @transaction.atomic
    def review(self, *, submission_id, action, reason):
        from hr_staff.services.material_service import MaterialService
        # Same lock order as submit: request, then submission.
        candidate = HrMaterialSubmission.objects.filter(tenant_id=self.tenant, pk=submission_id).first()
        if not candidate:
            raise CommandError("NOT_FOUND", "未找到补件回执", 404)
        request = HrMaterialRequest.objects.select_for_update().get(tenant_id=self.tenant, pk=candidate.request_id)
        item = HrMaterialSubmission.objects.select_for_update().select_related("material_version__material_id").get(
            tenant_id=self.tenant, pk=submission_id)
        if item.status != "SUBMITTED" or request.status != "SUBMITTED":
            raise CommandError("STATE_CONFLICT", "该回执已处理", 409)
        if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 512:
            raise CommandError("REASON_REQUIRED", "请填写512字以内的验收意见")
        assert_independent_reviewer(self.tenant, self.actor, request.target_staff_id_id, item.submitted_by)
        if action not in {"ACCEPT", "RETURN"}:
            raise CommandError("ACTION_INVALID", "只允许验收或退回")
        version = item.material_version
        if action == "ACCEPT":
            from hr_staff.services.evidence_reference_service import evidence_snapshot
            receipt = evidence_snapshot(self.tenant, request.target_staff_id_id, version.id, lock=True)
            if receipt["sha256"] != item.evidence_hash:
                raise CommandError("EVIDENCE_CHANGED", "材料已不匹配补件回执，不能验收", 409)
            if (version.sha256 != item.evidence_hash or version.material_id.current_version_id != version.id
                    or version.status != "CURRENT"):
                raise CommandError("EVIDENCE_CHANGED", "提交的材料版本已变化，须退回重交", 409)
            MaterialService(self.tenant, self.actor).verify_material(material_id=version.material_id_id,
                staff_id=request.target_staff_id_id)
        item.status = "ACCEPTED" if action == "ACCEPT" else "RETURNED"
        item.review_reason, item.reviewed_by, item.reviewed_at = reason.strip(), self.actor, timezone.now()
        item.save(update_fields=["status", "review_reason", "reviewed_by", "reviewed_at"])
        request.status = "VERIFIED" if action == "ACCEPT" else "REQUESTED"
        request.save(update_fields=["status", "updated_at"])
        self._audit(item, request.target_staff_id_id, "SelfMaterial" + item.status)
        return item

    def _audit(self, item, staff_id, action):
        write_audit_event(tenant_id=self.tenant, action=action, actor_user_id=self.actor,
            staff_id=staff_id, business_type="MATERIAL_REQUEST", business_id=str(item.request_id),
            reason=f"submission={item.id};revision={item.revision};status={item.status};sha256={item.evidence_hash}")
