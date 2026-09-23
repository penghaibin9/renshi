"""Authority workflow: SELF notice -> HR review -> existing exit saga -> fact.

No direct HR03/HR07/HR14 writes. Every mutation locks its authority row, requires
an expected version, and writes an append-only audit plus the registered outbox.
"""
from datetime import date
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from horilla.hr_event_service import emit_registered_event
from hr_exit.flex_models import RetirementFlexApplication as Application, RetirementFlexEvent, canonical_hash
from hr_exit.models import ExitCase, RetirementPrecheck, RetirementPolicy
from hr_exit.services.flex_rules import FlexRuleError, RULE_VERSION, add_months, validate_choice, validate_approval


class FlexError(ValueError):
    def __init__(self, code, message, status=400):
        self.code, self.status = code, status
        super().__init__(message)


def strict_uuid(value, name="id"):
    try:
        return UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        raise FlexError("FLEX_INPUT_INVALID", f"{name}必须是有效记录编号") from None


def strict_date(value, name="date"):
    try:
        return date.fromisoformat(str(value))
    except (ValueError, TypeError):
        raise FlexError("FLEX_DATE_INVALID", f"{name}必须是YYYY-MM-DD") from None


from hr_staff.constants import MaterialCategoryCode
from hr_staff.services.evidence_reference_service import evidence_snapshot
from hr_staff.services.material_service import MaterialService


class FlexRetirementService:
    OPEN = ("DRAFT", "SUBMITTED", "RETURNED")

    def __init__(self, tenant_id, actor_user_id):
        if not tenant_id or not actor_user_id:
            raise FlexError("FLEX_CONTEXT_REQUIRED", "学校和真实操作人不能为空", 403)
        self.tenant_id, self.actor = int(tenant_id), int(actor_user_id)

    def _get(self, application_id, *, staff_id=None):
        query = Application.objects.select_for_update().filter(
            tenant_id=self.tenant_id, id=strict_uuid(application_id))
        if staff_id is not None:
            query = query.filter(staff_id=staff_id)
        app = query.first()
        if app is None:
            raise FlexError("FLEX_NOT_FOUND", "当前学校和身份下未找到申请", 404)
        return app

    @staticmethod
    def _version(app, expected):
        if type(expected) is not int or expected != app.version:
            raise FlexError("FLEX_VERSION_CONFLICT", "记录已变化，请刷新后重试", 409)

    def _event(self, app, action, detail=None):
        payload = {"applicationId": str(app.id), "tenantId": self.tenant_id,
            "version": app.version, "status": app.status, "actorUserId": self.actor,
            "action": action, "detail": detail or {}, "at": timezone.now().isoformat()}
        RetirementFlexEvent.objects.create(tenant_id=self.tenant_id, application_id=app.id,
            version=app.version, action=action, payload=payload, content_hash=canonical_hash(payload),
            created_by=self.actor, updated_by=self.actor)
        emit_registered_event(tenant_id=self.tenant_id, event_name="hr.exit.flex.changed",
            payload={"applicationId": str(app.id), "version": app.version, "status": app.status, "action": action})

    def _save(self, app, action, detail=None):
        app.version += 1
        app.updated_by = self.actor
        app.save()
        self._event(app, action, detail)
        return app

    def _evidence(self, *, staff_id, version_id, category_code, label):
        evidence = evidence_snapshot(
            self.tenant_id, staff_id, version_id, lock=True
        )
        if evidence.get("categoryCode") != category_code:
            raise FlexError(
                "FLEX_EVIDENCE_CATEGORY_MISMATCH",
                f"{label}必须使用指定的人事材料分类，不能用其他材料替代",
                409,
            )
        return evidence

    @staticmethod
    def _assert_distinct_evidence(*evidence_items):
        rows = [item for item in evidence_items if item]
        version_ids = [item.get("versionId") for item in rows]
        material_ids = [item.get("materialId") for item in rows]
        if len(version_ids) != len(set(version_ids)) or len(material_ids) != len(set(material_ids)):
            raise FlexError(
                "FLEX_EVIDENCE_REUSED",
                "书面告知、审批依据、社保凭据和双方协议必须分别提供，不能重复引用同一材料",
                409,
            )

    def _verify_selected_evidence(self, *evidence_items, staff_id):
        service = MaterialService(self.tenant_id, self.actor)
        for item in (row for row in evidence_items if row):
            service.verify_material_version(
                material_id=item["materialId"],
                version_id=item["versionId"],
                staff_id=staff_id,
            )

    def _source(self, precheck_id, *, staff_id, require_active=True):
        from hr_staff.models import HrEmploymentRelationship
        from hr_exit.services.retirement_policy_service import _policy_retirement_age_months
        precheck = RetirementPrecheck.objects.filter(tenant_id=self.tenant_id,
            id=strict_uuid(precheck_id, "precheckId")).first()
        if precheck is None:
            raise FlexError("FLEX_PRECHECK_NOT_FOUND", "请先由人事部门完成本人的退休政策预审", 404)
        relationship = HrEmploymentRelationship.objects.select_for_update().select_related("staff_id__person_id").filter(
            tenant_id=self.tenant_id, id=precheck.employment_relationship_id,
            staff_id_id=staff_id, staff_id__tenant_id=self.tenant_id,
            staff_id__person_id_id=precheck.person_id,
        ).first()
        if relationship is None:
            raise FlexError("FLEX_SOURCE_NOT_FOUND", "预审不属于本校本人，或人事关系不存在", 404)
        if relationship.status != "ACTIVE":
            raise FlexError("FLEX_RELATIONSHIP_NOT_ACTIVE", "只有有效的人事关系可以申请退休", 409)
        reasons = set(precheck.explanation_json.get("reasonCodes") or [])
        if (precheck.decision not in {"ELIGIBLE", "NOT_YET"} or precheck.statutory_date is None
                or reasons - {"STATUTORY_DATE_NOT_REACHED"}):
            raise FlexError("FLEX_PRECHECK_MANUAL_REVIEW", "预审仍有未解决条件，需人事部门先复核", 409)
        policy = RetirementPolicy.objects.filter(tenant_id=self.tenant_id,
            id=precheck.matched_policy_id, version_no=precheck.matched_policy_version).first()
        if policy is None or not policy.content_hash or policy.content_hash != precheck.explanation_json.get("policyContentHash"):
            raise FlexError("FLEX_POLICY_STALE", "预审政策证据失效，请重新预审", 409)
        if require_active and policy.status != "ACTIVE":
            raise FlexError("FLEX_POLICY_STALE", "本校已更新退休政策，请按新政策重新预审", 409)
        person = relationship.staff_id.person_id
        base = policy.retirement_age_months
        # Only national ordinary cohorts are automatic. Never guess special
        # female senior-expert / cadre / special occupation policy applicability.
        if not person.birth_date or (person.gender_code, base) not in {("M", 720), ("F", 600), ("F", 660)} or policy.special_condition_code:
            raise FlexError("FLEX_SPECIAL_POLICY_REVIEW", "该人员涉及特殊退休口径，须专项核定，不能套用普通弹性规则", 409)
        calculated = add_months(person.birth_date, _policy_retirement_age_months(policy, person.birth_date))
        if calculated != precheck.statutory_date or precheck.as_of > timezone.localdate():
            raise FlexError("FLEX_SOURCE_STALE", "人员事实或预审日期无效，请重新预审", 409)
        snapshot = {"ruleVersion": RULE_VERSION, "precheckId": str(precheck.id),
            "policyId": str(policy.id), "policyVersion": policy.version_no, "policyHash": policy.content_hash,
            "statutoryDate": calculated.isoformat(), "originalMinimumDate": add_months(person.birth_date, base).isoformat(),
            "staffCategory": relationship.staff_id.staff_category_code,
            "personVersion": person.version, "staffVersion": relationship.staff_id.version,
            "relationshipVersion": relationship.version}
        return precheck, relationship, snapshot

    @transaction.atomic
    def create(self, *, staff_id, precheck_id, mode, requested_date, reason, idempotency_key, parent_id=None):
        staff_id = strict_uuid(staff_id, "staffId")
        key = str(idempotency_key or "").strip()
        reason = str(reason or "").strip()
        if not key or len(key) > 128 or not 1 <= len(reason) <= 1000:
            raise FlexError("FLEX_INPUT_INVALID", "须提供请求编号和1000字以内申请说明")
        mode = str(mode or "").upper()
        requested_date = strict_date(requested_date, "requestedDate")
        precheck_id = strict_uuid(precheck_id, "precheckId")
        parent_id = strict_uuid(parent_id, "parentApplicationId") if parent_id else None
        payload = {"precheckId": str(precheck_id), "mode": mode, "requestedDate": requested_date.isoformat(),
            "reason": reason, "parentId": str(parent_id) if parent_id else None}
        request_hash = canonical_hash(payload)
        # Lock an existing Authority subject; locking an absent idempotency key
        # alone would not serialize concurrent first submissions on MySQL.
        from hr_staff.models import HrStaffMaster
        staff = HrStaffMaster.objects.select_for_update().filter(id=staff_id, tenant_id=self.tenant_id).first()
        if staff is None:
            raise FlexError("FLEX_SOURCE_NOT_FOUND", "本人主档不存在", 404)
        existing = Application.objects.filter(tenant_id=self.tenant_id, staff_id=staff_id, idempotency_key=key).first()
        if existing:
            if existing.request_hash != request_hash:
                raise FlexError("FLEX_IDEMPOTENCY_CONFLICT", "请求编号已用于不同申请", 409)
            return existing, False
        precheck, relationship, snapshot = self._source(precheck_id, staff_id=staff_id, require_active=(mode != "END_DELAY"))
        parent = None
        if mode == "END_DELAY":
            parent = self._get(parent_id, staff_id=staff_id)
            if (parent.mode != "DELAY" or parent.status != "APPROVED" or not parent.verify_seal()
                    or parent.employment_relationship_id != relationship.id or parent.precheck_id != precheck.id):
                raise FlexError("FLEX_PARENT_INVALID", "必须引用本人已批准的延迟退休申请", 409)
            snapshot = dict(parent.authority_snapshot)
        elif parent_id:
            raise FlexError("FLEX_PARENT_INVALID", "仅终止延迟申请可以引用原申请")
        blocked = Application.objects.filter(tenant_id=self.tenant_id, employment_relationship_id=relationship.id,
            status__in=(*self.OPEN, "APPROVED"))
        if mode == "END_DELAY":
            blocked = blocked.filter(mode="END_DELAY")
        if blocked.exists():
            raise FlexError("FLEX_ALREADY_OPEN", "该人事关系已有待办或已批准申请，不得重复申请或再次延长", 409)
        self._choice(mode, requested_date, snapshot, timezone.localdate(), parent)
        app = Application.objects.create(tenant_id=self.tenant_id, staff_id=staff_id,
            person_id=precheck.person_id, employment_relationship_id=relationship.id,
            precheck_id=precheck.id, parent_application_id=parent_id, mode=mode,
            requested_date=requested_date, reason=reason, idempotency_key=key,
            request_hash=request_hash, authority_snapshot=snapshot, created_by=self.actor, updated_by=self.actor)
        self._event(app, "DRAFTED")
        return app, True

    def _choice(self, mode, requested, snapshot, notice_date, parent=None):
        try:
            validate_choice(mode=mode, requested_date=requested,
                statutory_date=strict_date(snapshot.get("statutoryDate")),
                original_minimum_date=strict_date(snapshot.get("originalMinimumDate")),
                notice_date=notice_date, today=timezone.localdate(),
                parent_date=parent.requested_date if parent else None)
        except FlexRuleError as exc:
            raise FlexError(exc.code, str(exc), 409) from exc

    @transaction.atomic
    def submit(self, application_id, *, staff_id, expected_version, notice_version_id):
        app = self._get(application_id, staff_id=staff_id)
        self._version(app, expected_version)
        if app.status not in self.OPEN or app.status == "SUBMITTED":
            raise FlexError("FLEX_STATE_CONFLICT", "只有草稿或退回申请可提交", 409)
        self._source(app.precheck_id, staff_id=app.staff_id, require_active=(app.mode != "END_DELAY"))
        parent = self._get(app.parent_application_id, staff_id=staff_id) if app.parent_application_id else None
        # Preserve the first written notice; supplements do not erase its date.
        notice_date = app.notice_date or timezone.localdate()
        self._choice(app.mode, app.requested_date, app.authority_snapshot, notice_date, parent)
        evidence = self._evidence(
            staff_id=app.staff_id,
            version_id=notice_version_id,
            category_code=MaterialCategoryCode.RETIREMENT_NOTICE,
            label="本人书面告知材料",
        )
        app.notice_date = notice_date
        app.notice_material_version_id = strict_uuid(notice_version_id)
        app.status = "SUBMITTED"
        return self._save(app, "SUBMITTED", {"noticeEvidence": evidence})

    @transaction.atomic
    def cancel(self, application_id, *, staff_id, expected_version):
        app = self._get(application_id, staff_id=staff_id)
        self._version(app, expected_version)
        if app.status not in self.OPEN:
            raise FlexError("FLEX_STATE_CONFLICT", "已批准申请不能直接撤销；延迟期间可另行协商终止", 409)
        app.status = "CANCELLED"
        return self._save(app, "CANCELLED")

    @transaction.atomic
    def review(self, application_id, *, expected_version, action, reason, review=None):
        app = self._get(application_id)
        self._version(app, expected_version)
        if app.status != "SUBMITTED":
            raise FlexError("FLEX_STATE_CONFLICT", "仅待审批申请可处理", 409)
        # HR17 is unavailable to unlinked users; for managers also reject any
        # login resolving to the same staff, not only the original submitting ID.
        if app.created_by == self.actor:
            raise FlexError("FLEX_SELF_APPROVAL_FORBIDDEN", "不得审核本人的退休申请", 403)
        from django.contrib.auth import get_user_model
        from hr_self.services.identity_service import SelfIdentityService, SelfIdentityError
        reviewer = get_user_model().objects.filter(pk=self.actor, is_active=True).first()
        if reviewer is None:
            raise FlexError("FLEX_REVIEWER_INACTIVE", "审批人不存在或已停用", 403)
        try:
            identity = SelfIdentityService(self.tenant_id).resolve(reviewer)
        except SelfIdentityError as exc:
            if exc.code == "SELF_IDENTITY_AMBIGUOUS":
                raise FlexError("REVIEWER_IDENTITY_AMBIGUOUS", "审批人身份存在歧义，须先治理", 403) from exc
            identity = None
        if identity is not None and str(identity.staff_id) == str(app.staff_id):
            raise FlexError("FLEX_SELF_APPROVAL_FORBIDDEN", "不得审核本人的退休申请", 403)
        reason = str(reason or "").strip()
        if not 1 <= len(reason) <= 1000:
            raise FlexError("FLEX_REVIEW_REASON_REQUIRED", "须填写1000字以内核验意见")
        if action in {"RETURN", "REJECT"}:
            app.status = "RETURNED" if action == "RETURN" else "REJECTED"
            return self._save(app, action, {"reason": reason})
        if action != "APPROVE" or not isinstance(review, dict):
            raise FlexError("FLEX_ACTION_INVALID", "不支持的审批动作")
        _, _, source = self._source(app.precheck_id, staff_id=app.staff_id, require_active=(app.mode != "END_DELAY"))
        if source != app.authority_snapshot and app.mode != "END_DELAY":
            raise FlexError("FLEX_SOURCE_STALE", "申请后人员或政策事实已变化，请重新预审申请", 409)
        parent = self._get(app.parent_application_id, staff_id=app.staff_id) if app.parent_application_id else None
        self._choice(app.mode, app.requested_date, app.authority_snapshot, app.notice_date, parent)
        notice = self._evidence(
            staff_id=app.staff_id,
            version_id=app.notice_material_version_id,
            category_code=MaterialCategoryCode.RETIREMENT_NOTICE,
            label="本人书面告知材料",
        )
        approval = self._evidence(
            staff_id=app.staff_id,
            version_id=review.get("approvalMaterialVersionId"),
            category_code=MaterialCategoryCode.RETIREMENT_APPROVAL,
            label="人事审批依据",
        )
        contribution = self._evidence(
            staff_id=app.staff_id,
            version_id=review.get("contributionMaterialVersionId"),
            category_code=MaterialCategoryCode.RETIREMENT_CONTRIBUTION,
            label="社保缴费核验材料",
        )
        agreement = (
            self._evidence(
                staff_id=app.staff_id,
                version_id=review.get("agreementMaterialVersionId"),
                category_code=MaterialCategoryCode.RETIREMENT_AGREEMENT,
                label="单位与本人书面协议",
            )
            if app.mode != "EARLY"
            else None
        )
        self._assert_distinct_evidence(notice, approval, contribution, agreement)
        agreement_date = strict_date(review.get("agreementDate")) if agreement else None
        if app.mode in {"DELAY", "END_DELAY"} and source.get("staffCategory") == "ADMIN":
            raise FlexError("FLEX_ADMIN_CAPACITY_REVIEW", "主档为行政人员，不能按普通专业技术人员放行弹性延迟；须先核定适用身份", 409)
        try:
            checked = validate_approval(mode=app.mode, requested_date=app.requested_date,
                statutory_date=strict_date(app.authority_snapshot["statutoryDate"]),
                capacity=review.get("capacity"), contribution_months=review.get("contributionMonths"),
                agreement_date=agreement_date, today=timezone.localdate(),
                has_approval_evidence=bool(approval), has_contribution_evidence=bool(contribution),
                has_agreement_evidence=bool(agreement))
        except FlexRuleError as exc:
            raise FlexError(exc.code, str(exc), 409) from exc
        # Verification is recorded against the exact immutable versions sealed
        # into this approval, never whichever file happens to be current later.
        self._verify_selected_evidence(
            notice, approval, contribution, agreement, staff_id=app.staff_id
        )
        # Re-snapshot after verification so the sealed decision records the
        # reviewer and verification timestamp for every selected evidence row.
        notice = self._evidence(
            staff_id=app.staff_id, version_id=notice["versionId"],
            category_code=MaterialCategoryCode.RETIREMENT_NOTICE, label="本人书面告知材料"
        )
        approval = self._evidence(
            staff_id=app.staff_id, version_id=approval["versionId"],
            category_code=MaterialCategoryCode.RETIREMENT_APPROVAL, label="人事审批依据"
        )
        contribution = self._evidence(
            staff_id=app.staff_id, version_id=contribution["versionId"],
            category_code=MaterialCategoryCode.RETIREMENT_CONTRIBUTION, label="社保缴费核验材料"
        )
        agreement = (
            self._evidence(
                staff_id=app.staff_id, version_id=agreement["versionId"],
                category_code=MaterialCategoryCode.RETIREMENT_AGREEMENT, label="单位与本人书面协议"
            ) if agreement else None
        )
        app.review_snapshot = {**checked, "capacity": review.get("capacity"), "reason": reason,
            "noticeEvidence": notice, "approvalEvidence": approval, "contributionEvidence": contribution,
            "agreementEvidence": agreement, "agreementDate": agreement_date.isoformat() if agreement_date else None}
        app.approved_by, app.approved_at = self.actor, timezone.now()
        app.status = "APPROVED"
        app.approval_hash = canonical_hash(app.approval_payload())
        return self._save(app, "APPROVED", {"approvalHash": app.approval_hash})

    @transaction.atomic
    def open_exit_case(self, application_id, *, expected_version):
        from hr_exit.services.case_service import ExitCaseService, ExitCaseInput
        app = self._get(application_id)
        self._version(app, expected_version)
        if app.status != "APPROVED" or not app.verify_seal():
            raise FlexError("FLEX_APPROVAL_REQUIRED", "须先完成有效的独立核验审批", 409)
        if app.exit_case_id:
            return app
        service = ExitCaseService(self.tenant_id, self.actor)
        parent = self._get(app.parent_application_id) if app.parent_application_id else None
        event_action = "EXIT_CASE_OPENED"
        detail = {}
        if parent and parent.exit_case_id:
            # END_DELAY is a sealed successor decision.  Reuse the original exit
            # case, but reopen any already-submitted/approved plan for normal
            # review instead of silently changing an approved date.  Handover
            # work and effect/settlement facts remain fail-closed.
            case, prior = service.revise_retirement_plan_for_successor(
                parent.exit_case_id,
                requested_date=app.requested_date,
                last_working_date=app.requested_date,
                planned_employment_end_date=app.requested_date,
            )
            event_action = "EXIT_CASE_REPLANNED"
            detail = {
                "caseId": str(case.id),
                "previousPlan": prior,
                "reopenedStatus": case.status,
                "newPlanDate": app.requested_date.isoformat(),
            }
        else:
            case = service.create_draft(ExitCaseInput(case_no=f"FLEX-{app.id.hex}",
                person_id=app.person_id, employment_relationship_id=app.employment_relationship_id,
                exit_type=ExitCase.ExitType.RETIREMENT, requested_date=app.requested_date,
                last_working_date=app.requested_date, planned_employment_end_date=app.requested_date))
            detail = {"caseId": str(case.id)}
        app.exit_case_id = case.id
        return self._save(app, event_action, detail)


def approved_plan_for_case(tenant_id, case_id):
    plans = list(Application.objects.filter(tenant_id=tenant_id, exit_case_id=case_id, status="APPROVED")
        .order_by("-approved_at", "-id")[:3])
    if not plans:
        return None
    terminations = [p for p in plans if p.mode == "END_DELAY"]
    selected = terminations[0] if terminations else plans[0]
    if selected.mode == "DELAY" and Application.objects.filter(tenant_id=tenant_id,
            parent_application_id=selected.id, mode="END_DELAY", status="APPROVED").exclude(exit_case_id=case_id).exists():
        raise FlexError("FLEX_TERMINATION_LINK_REQUIRED", "已有批准的终止延迟决定，须先更新关联离校计划", 409)
    if not selected.verify_seal():
        raise FlexError("FLEX_APPROVAL_SEAL_INVALID", "弹性退休审批证据校验失败", 409)
    return selected


def validate_retirement_effect(tenant_id, case):
    """Run BEFORE HR03 termination, never after an irreversible formal effect."""
    if case.exit_type != ExitCase.ExitType.RETIREMENT:
        return
    if not case.planned_employment_end_date:
        raise FlexError("RETIREMENT_DATE_REQUIRED", "须先确定计划退休日期", 409)
    if case.planned_employment_end_date > timezone.localdate():
        raise FlexError("RETIREMENT_EFFECT_NOT_DUE", "退休日期尚未到达，不能提前结束人事关系", 409)
    plan = approved_plan_for_case(tenant_id, case.id)
    if plan:
        if (plan.person_id != case.person_id or plan.employment_relationship_id != case.employment_relationship_id
                or plan.requested_date != case.planned_employment_end_date):
            raise FlexError("FLEX_EFFECT_DATE_CONFLICT", "离校计划与已批准弹性退休事实不一致", 409)
        return
    # An approved delay cannot be bypassed by creating a second ordinary case.
    if Application.objects.filter(tenant_id=tenant_id, employment_relationship_id=case.employment_relationship_id,
            status="APPROVED").exists():
        raise FlexError("FLEX_EXIT_LINK_REQUIRED", "须从已批准的弹性退休申请进入离校办理", 409)
    if not RetirementPrecheck.objects.filter(tenant_id=tenant_id, person_id=case.person_id,
            employment_relationship_id=case.employment_relationship_id, decision="ELIGIBLE",
            statutory_date=case.planned_employment_end_date, as_of__lte=case.planned_employment_end_date).exists():
        raise FlexError("RETIREMENT_PRECHECK_REQUIRED", "正式结束人事关系前须有同人、同日期的合格预审或批准的弹性退休申请", 409)
