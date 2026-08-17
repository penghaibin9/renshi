"""
hr_recruitment/services/application_service.py

HR04-03 应聘申请服务（《04_HR04_总册》§10.4/§14/§49）。

流程（§49 公开报名可靠性）：
  save draft → upload materials → validate required → submit transaction
  → generate application_no → freeze referenced versions → emit outbox event → acknowledge

硬规则：
- 提交幂等：Idempotency-Key + unique(tenant, candidate, position, active)。
- 状态变化必须写 HrApplicationTransition ledger（§14.3）。
- 已提交 Application 冻结公告/资格/评分方案版本（不可静默改）。
- 撤回 = 候选主动动作（WITHDRAWN）；不占 active 唯一约束。
"""

from __future__ import annotations

import hashlib
from datetime import date
from uuid import uuid4

from django.db import IntegrityError, transaction
from django.utils import timezone

from hr_recruitment.api.exceptions import (
    ApplicationAlreadySubmittedError,
    InvalidStateTransitionError,
    PositionCapacityConflictError,
)
from hr_recruitment.constants import ApplicationCanonicalStatus as S
from hr_recruitment.models import HrApplicationMaterial, HrJobApplication
from hr_recruitment.policies.state_machine import assert_transition


class ApplicationServiceError(Exception):
    def __init__(self, code: str, message: str, *, http_status: int = 422):
        self.code = code
        self.message = message
        self.http_status = http_status
        super().__init__(message)


class ApplicationService:
    def __init__(self, *, tenant_id: int, actor: str = ""):
        self.tenant_id = tenant_id
        self.actor = actor

    @transaction.atomic
    def save_draft(
        self,
        *,
        candidate_id: str,
        recruitment_position_id: str,
        form_data: dict | None = None,
        application_id: str | None = None,
    ) -> HrJobApplication:
        """保存草稿（幂等：同 candidate+position 的 active DRAFT 复用）。"""
        if application_id:
            try:
                app = HrJobApplication.objects.select_for_update().get(
                    id=application_id, tenant_id=self.tenant_id
                )
            except HrJobApplication.DoesNotExist:
                raise ApplicationServiceError("APPLICATION_NOT_FOUND", "申请不存在", http_status=404)
            if app.canonical_status != S.DRAFT:
                raise ApplicationAlreadySubmittedError("申请已提交，不可修改草稿")
        else:
            app = (
                HrJobApplication.objects.filter(
                    tenant_id=self.tenant_id,
                    candidate_id_id=candidate_id,
                    recruitment_position_id_id=recruitment_position_id,
                    canonical_status=S.DRAFT,
                    is_active=True,
                )
                .select_for_update()
                .first()
            )
            if app is None:
                # 同候选+同岗位已有 active 非 DRAFT 申请 → 409（不撞 unique 抛 500）
                existing_active = HrJobApplication.objects.filter(
                    tenant_id=self.tenant_id,
                    candidate_id_id=candidate_id,
                    recruitment_position_id_id=recruitment_position_id,
                    is_active=True,
                ).first()
                if existing_active is not None:
                    raise ApplicationAlreadySubmittedError(
                        "该候选人已存在进行中的申请，不可重复创建草稿"
                    )
                app = HrJobApplication.objects.create(
                    tenant_id=self.tenant_id,
                    candidate_id_id=candidate_id,
                    recruitment_position_id_id=recruitment_position_id,
                    canonical_status=S.DRAFT,
                    source_channel="PUBLIC_PORTAL",
                    form_snapshot=form_data or {},
                )
        if form_data is not None:
            app.form_snapshot = {**app.form_snapshot, **form_data}
            app.save(update_fields=["form_snapshot"])
        return app

    @transaction.atomic
    def submit(
        self,
        *,
        application_id: str,
        idempotency_key: str | None = None,
    ) -> HrJobApplication:
        """正式提交（幂等：Idempotency-Key 落库 + active 唯一约束，冻结版本 + ledger）。"""
        app = (
            HrJobApplication.objects.select_for_update()
            .filter(id=application_id, tenant_id=self.tenant_id)
            .first()
        )
        if app is None:
            raise ApplicationServiceError("APPLICATION_NOT_FOUND", "申请不存在", http_status=404)

        # Idempotency-Key 幂等：同 key 已提交 → 返回原申请（§49 公开报名可靠性）
        if idempotency_key:
            from hr_recruitment.models import HrApplicationSubmissionKey

            recorded = HrApplicationSubmissionKey.objects.filter(
                tenant_id=self.tenant_id, idempotency_key=idempotency_key
            ).first()
            if recorded is not None:
                return recorded.application_id

        if app.canonical_status == S.SUBMITTED:
            # 已提交（同申请重放）：记录 key 后返回
            if idempotency_key:
                self._record_submission_key(idempotency_key, app)
            return app
        if app.canonical_status != S.DRAFT:
            # 已推进（重试/并发）：幂等语义下返回原对象，不因状态推进而 409
            if idempotency_key:
                self._record_submission_key(idempotency_key, app)
            return app

        assert_transition(app.canonical_status, S.SUBMITTED)
        app.canonical_status = S.SUBMITTED
        app.submitted_at = timezone.now()
        # 生成 application_no（tenant 内唯一）
        app.application_no = self._generate_application_no()
        # 冻结版本（§49）：公告/资格/评分方案引用当前 ACTIVE 版本
        app = self._freeze_versions(app)
        app.version += 1
        try:
            app.save()
        except IntegrityError:
            raise ApplicationAlreadySubmittedError("重复提交：同岗位存在 active 申请")

        if idempotency_key:
            self._record_submission_key(idempotency_key, app)

        # ledger（§14.3）
        from hr_recruitment.models import HrApplicationTransition

        HrApplicationTransition.objects.create(
            tenant_id=self.tenant_id,
            application_id=app,
            from_status=S.DRAFT,
            to_status=S.SUBMITTED,
            action="SUBMIT",
            actor_id=self.actor,
            source="PUBLIC_PORTAL" if not self.actor else "ADMIN",
        )
        return app

    def _record_submission_key(self, idempotency_key: str, app) -> None:
        """幂等键落库（unique(tenant, key)），重复提交命中返回原申请。"""
        from hr_recruitment.models import HrApplicationSubmissionKey

        try:
            HrApplicationSubmissionKey.objects.create(
                tenant_id=self.tenant_id,
                idempotency_key=idempotency_key,
                application_id=app,
            )
        except IntegrityError:
            pass  # 并发重复：已存在，无需处理

    def _generate_application_no(self) -> str:
        while True:
            no = f"APP-{timezone.now().strftime('%Y%m%d')}-{uuid4().hex[:6].upper()}"
            if not HrJobApplication.objects.filter(
                tenant_id=self.tenant_id, application_no=no
            ).exists():
                return no

    def _freeze_versions(self, app: HrJobApplication) -> HrJobApplication:
        """
        冻结公告/资格/评分方案版本（发布后不可静默改，§49/§51）。

        fail-closed：岗位存在任何 DRAFT 规则集/方案但无 ACTIVE 版本 → 阻断提交（禁止"无规则依据"报名）。
        """
        from hr_recruitment.models import (
            HrQualificationRuleSetVersion,
            HrRecruitmentAnnouncementVersion,
            HrSelectionSchemeVersion,
        )

        campaign = app.recruitment_position_id.campaign_id
        last_ann = (
            HrRecruitmentAnnouncementVersion.objects.filter(
                tenant_id=self.tenant_id, campaign_id=campaign
            )
            .order_by("-version_no")
            .first()
        )
        if last_ann is not None and last_ann.published_at is None:
            raise ApplicationServiceError(
                "ANNOUNCEMENT_NOT_PUBLISHED", "公告尚未发布，禁止提交申请", http_status=409
            )
        if last_ann is not None and last_ann.published_at:
            app.announcement_version_id = last_ann.id

        qual_any = HrQualificationRuleSetVersion.objects.filter(
            tenant_id=self.tenant_id,
            recruitment_position_id=app.recruitment_position_id,
        ).exists()
        qual = (
            HrQualificationRuleSetVersion.objects.filter(
                tenant_id=self.tenant_id,
                recruitment_position_id=app.recruitment_position_id,
                status="ACTIVE",
            )
            .order_by("-version_no")
            .first()
        )
        if qual_any and qual is None:
            raise ApplicationServiceError(
                "QUALIFICATION_RULES_NOT_ACTIVE",
                "岗位已配置资格条件但未发布 ACTIVE 版本，禁止提交申请",
                http_status=409,
            )
        if qual:
            app.qualification_rule_version_id = qual.id

        scheme_any = HrSelectionSchemeVersion.objects.filter(
            tenant_id=self.tenant_id,
            recruitment_position_id=app.recruitment_position_id,
        ).exists()
        scheme = (
            HrSelectionSchemeVersion.objects.filter(
                tenant_id=self.tenant_id,
                recruitment_position_id=app.recruitment_position_id,
                status="ACTIVE",
            )
            .order_by("-version_no")
            .first()
        )
        if scheme_any and scheme is None:
            raise ApplicationServiceError(
                "SELECTION_SCHEME_NOT_ACTIVE",
                "岗位已配置评分方案但未发布 ACTIVE 版本，禁止提交申请",
                http_status=409,
            )
        if scheme:
            app.selection_scheme_version_id = scheme.id
        return app

    @transaction.atomic
    def withdraw(self, *, application_id: str) -> HrJobApplication:
        """候选主动撤回（WITHDRAWN；不占 active 唯一）。"""
        app = (
            HrJobApplication.objects.select_for_update()
            .filter(id=application_id, tenant_id=self.tenant_id)
            .first()
        )
        if app is None:
            raise ApplicationServiceError("APPLICATION_NOT_FOUND", "申请不存在", http_status=404)
        from_status = app.canonical_status
        assert_transition(from_status, S.WITHDRAWN)
        app.canonical_status = S.WITHDRAWN
        app.withdrawn_at = timezone.now()
        app.is_active = False
        app.version += 1
        app.save(update_fields=["canonical_status", "withdrawn_at", "is_active", "version"])
        from hr_recruitment.models import HrApplicationTransition

        HrApplicationTransition.objects.create(
            tenant_id=self.tenant_id,
            application_id=app,
            from_status=from_status,
            to_status=S.WITHDRAWN,
            action="WITHDRAW",
            actor_id=self.actor,
            source="CANDIDATE" if not self.actor else "ADMIN",
        )
        return app

    @transaction.atomic
    def add_material(
        self,
        *,
        application_id: str,
        material_type: str,
        title: str,
        file_name: str,
        file_path: str,
        sha256: str = "",
        mime_type: str = "",
        file_size_bytes: int = 0,
        sensitive_level: str = "RESTRICTED_HR",
    ) -> HrApplicationMaterial:
        """添加材料（版本化：同类型同标题递增版本；提交后禁止增改；sensitive_level 服务端校验）。"""
        app = HrJobApplication.objects.filter(
            id=application_id, tenant_id=self.tenant_id
        ).first()
        if app is None:
            raise ApplicationServiceError("APPLICATION_NOT_FOUND", "申请不存在", http_status=404)
        # 已提交/已推进的申请禁止增改材料（§49：提交后冻结）
        if app.canonical_status != S.DRAFT:
            raise ApplicationServiceError(
                "APPLICATION_SUBMITTED", "申请已提交，材料已冻结，不可增改", http_status=409
            )
        # sensitive_level 服务端枚举校验（不信任客户端任意值）
        from hr_recruitment.constants import SensitiveLevel

        allowed_levels = set(SensitiveLevel.values)
        if sensitive_level not in allowed_levels:
            raise ApplicationServiceError(
                "INVALID_SENSITIVE_LEVEL", "非法材料敏感级", http_status=422
            )
        last = (
            HrApplicationMaterial.objects.filter(
                tenant_id=self.tenant_id,
                application_id=app,
                material_type=material_type,
                title=title,
            )
            .order_by("-version_no")
            .first()
        )
        version_no = (last.version_no if last else 0) + 1
        material = HrApplicationMaterial.objects.create(
            tenant_id=self.tenant_id,
            application_id=app,
            material_type=material_type,
            title=title,
            version_no=version_no,
            file_name=file_name,
            file_path=file_path,
            sha256=sha256 or hashlib.sha256(file_path.encode()).hexdigest(),
            mime_type=mime_type,
            file_size_bytes=file_size_bytes,
            sensitive_level=sensitive_level,
            supersedes_id=last if last else None,
            created_by=self.actor,
        )
        return material
