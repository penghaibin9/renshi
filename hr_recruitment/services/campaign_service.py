"""
hr_recruitment/services/campaign_service.py

HR04-02 招聘项目与岗位服务（《04_HR04_总册》§9）。

Campaign 状态机（§9.4）：
  DRAFT → UNDER_APPROVAL → APPROVED → PUBLISHED → OPEN → CLOSED → COMPLETED → ARCHIVED

Position 状态机（§9.5）：
  DRAFT → READY → OPEN → CLOSED → SELECTION → PROPOSED_HIRE → FILLED / PARTIALLY_FILLED / CANCELLED

硬规则：
- READY/OPEN 前必须预占 HR02 额度（§9.6）；未预占不可开放报名。
- 招聘取消/关闭未录用额度必须 release。
- 公告发布后 immutable；amendment 新建版本（§51）。
- vacancy 只是展示值，额度权威在 HR02 Reservation。
"""

from __future__ import annotations

from uuid import uuid4

from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from hr_recruitment.api.exceptions import (
    InvalidStateTransitionError,
    PositionCapacityConflictError,
)
from hr_recruitment.constants import CampaignStatus, RecruitmentPositionStatus
from hr_recruitment.integrations.hr02 import (
    Hr02CapacityProvider,
    Hr02ReservationProvider,
)
from hr_recruitment.models import (
    HrRecruitmentAnnouncementVersion,
    HrRecruitmentCampaign,
    HrRecruitmentPosition,
)

SOURCE_BUSINESS_TYPE = "recruitment_position"


class CampaignServiceError(Exception):
    def __init__(self, code: str, message: str, *, http_status: int = 422):
        self.code = code
        self.message = message
        self.http_status = http_status
        super().__init__(message)


class CampaignService:
    CAMPAIGN_ALLOWED = {
        CampaignStatus.DRAFT: {CampaignStatus.UNDER_APPROVAL, CampaignStatus.ARCHIVED},
        CampaignStatus.UNDER_APPROVAL: {CampaignStatus.APPROVED, CampaignStatus.DRAFT},
        CampaignStatus.APPROVED: {CampaignStatus.PUBLISHED, CampaignStatus.CLOSED},
        CampaignStatus.PUBLISHED: {CampaignStatus.OPEN, CampaignStatus.CLOSED},
        CampaignStatus.OPEN: {CampaignStatus.CLOSED, CampaignStatus.RESULT_PROCESSING},
        CampaignStatus.CLOSED: {CampaignStatus.RESULT_PROCESSING, CampaignStatus.COMPLETED},
        CampaignStatus.RESULT_PROCESSING: {CampaignStatus.COMPLETED, CampaignStatus.OPEN},
        CampaignStatus.COMPLETED: {CampaignStatus.ARCHIVED},
        CampaignStatus.ARCHIVED: set(),
    }

    POSITION_ALLOWED = {
        RecruitmentPositionStatus.DRAFT: {RecruitmentPositionStatus.READY, RecruitmentPositionStatus.CANCELLED},
        RecruitmentPositionStatus.READY: {RecruitmentPositionStatus.OPEN, RecruitmentPositionStatus.CANCELLED},
        RecruitmentPositionStatus.OPEN: {RecruitmentPositionStatus.CLOSED, RecruitmentPositionStatus.SELECTION},
        RecruitmentPositionStatus.CLOSED: {RecruitmentPositionStatus.SELECTION, RecruitmentPositionStatus.CANCELLED},
        RecruitmentPositionStatus.SELECTION: {
            RecruitmentPositionStatus.PROPOSED_HIRE,
            RecruitmentPositionStatus.CLOSED,
        },
        RecruitmentPositionStatus.PROPOSED_HIRE: {
            RecruitmentPositionStatus.FILLED,
            RecruitmentPositionStatus.PARTIALLY_FILLED,
        },
        RecruitmentPositionStatus.FILLED: set(),
        RecruitmentPositionStatus.PARTIALLY_FILLED: {RecruitmentPositionStatus.FILLED},
        RecruitmentPositionStatus.CANCELLED: set(),
    }

    def __init__(self, *, tenant_id: int, actor: str = ""):
        self.tenant_id = tenant_id
        self.actor = actor

    # ---- Campaign ----

    @transaction.atomic
    def create_campaign(
        self,
        *,
        code,
        title,
        campaign_type,
        plan_cycle_id=None,
        application_open_at=None,
        application_close_at=None,
        timezone="Asia/Shanghai",
        manager_employee_ids=None,
        description="",
    ) -> HrRecruitmentCampaign:
        if HrRecruitmentCampaign.objects.filter(tenant_id=self.tenant_id, code=code).exists():
            raise CampaignServiceError("CAMPAIGN_CODE_DUPLICATE", f"招聘项目编号 {code} 已存在", http_status=409)
        public_slug = slugify(title) or f"recruit-{uuid4().hex[:8]}"
        # 防 slug 冲突
        while HrRecruitmentCampaign.objects.filter(
            tenant_id=self.tenant_id, public_slug=public_slug
        ).exists():
            public_slug = f"{slugify(title)}-{uuid4().hex[:4]}"
        # 公开 token：全局唯一不透明串（A0 解析键，不依赖 tenant_id 客户端传值）
        public_token = uuid4().hex
        while HrRecruitmentCampaign.objects.filter(public_token=public_token).exists():
            public_token = uuid4().hex
        return HrRecruitmentCampaign.objects.create(
            tenant_id=self.tenant_id,
            code=code,
            title=title,
            campaign_type=campaign_type,
            plan_cycle_id=plan_cycle_id,
            status=CampaignStatus.DRAFT,
            public_slug=public_slug,
            public_token=public_token,
            application_open_at=application_open_at,
            application_close_at=application_close_at,
            timezone=timezone,
            manager_employee_ids=manager_employee_ids or [],
            description=description,
            created_by=self.actor,
        )

    def _assert_campaign(self, campaign, target: str) -> None:
        allowed = self.CAMPAIGN_ALLOWED.get(campaign.status, set())
        if target not in allowed:
            raise InvalidStateTransitionError(
                f"非法招聘项目状态迁移: {campaign.status} -> {target}"
            )

    def transition_campaign(self, campaign_id: str, *, target: str) -> HrRecruitmentCampaign:
        campaign = self._get_campaign(campaign_id)
        self._assert_campaign(campaign, target)
        campaign.status = target
        campaign.version += 1
        campaign.save(update_fields=["status", "version"])
        # 关闭/完成招聘时释放未用于拟录用的 HELD 预占（§36 关闭释放未使用 reservation）
        if target in (CampaignStatus.CLOSED, CampaignStatus.COMPLETED):
            self._release_unused_reservations(campaign)
        return campaign

    def _release_unused_reservations(self, campaign: HrRecruitmentCampaign) -> None:
        """释放该招聘项目下未进入拟录用流程的岗位 HELD 预占。"""
        from hr_recruitment.models import HrProposedHire

        positions = list(
            HrRecruitmentPosition.objects.filter(
                tenant_id=self.tenant_id, campaign_id=campaign
            ).exclude(status=RecruitmentPositionStatus.CANCELLED)
        )
        proposed_position_ids = set(
            HrProposedHire.objects.filter(
                tenant_id=self.tenant_id,
                recruitment_position_id__in=positions,
            ).values_list("recruitment_position_id_id", flat=True)
        )
        from hr_recruitment.integrations.hr02 import Hr02ReservationProvider

        provider = Hr02ReservationProvider(tenant_id=self.tenant_id, actor=self.actor)
        for position in positions:
            if not position.reservation_id:
                continue
            if str(position.id) in proposed_position_ids:
                continue  # 有拟录用，预占保留（由 handoff commit 或后续处理）
            try:
                provider.release(position.reservation_id)
            except Exception:  # noqa: BLE001
                continue
            position.reservation_id = ""
            position.reservation_no = ""
            position.reserved_headcount = 0
            position.save(
                update_fields=["reservation_id", "reservation_no", "reserved_headcount"]
            )

    def _get_campaign(self, campaign_id: str) -> HrRecruitmentCampaign:
        try:
            return HrRecruitmentCampaign.objects.get(
                id=campaign_id, tenant_id=self.tenant_id
            )
        except HrRecruitmentCampaign.DoesNotExist:
            raise CampaignServiceError("CAMPAIGN_NOT_FOUND", "招聘项目不存在", http_status=404)

    @transaction.atomic
    def create_from_plan(
        self,
        *,
        plan_cycle_id: str,
        code: str,
        title: str,
        campaign_type: str = "MULTI_POSITION",
        application_open_at=None,
        application_close_at=None,
        timezone="Asia/Shanghai",
    ) -> HrRecruitmentCampaign:
        """从已批准年度计划创建招聘项目（§9.1 / §36 验收）。"""
        from hr_recruitment.constants import PlanLineStatus, PlanRequestStatus
        from hr_recruitment.models import HrHiringPlanCycle, HrHiringPlanLine

        cycle = HrHiringPlanCycle.objects.filter(
            tenant_id=self.tenant_id, id=plan_cycle_id
        ).first()
        if cycle is None:
            raise CampaignServiceError("PLAN_CYCLE_NOT_FOUND", "计划周期不存在", http_status=404)
        approved_lines = HrHiringPlanLine.objects.filter(
            tenant_id=self.tenant_id,
            request_id__cycle_id=cycle,
            request_id__status__in=[
                PlanRequestStatus.APPROVED,
                PlanRequestStatus.PARTIALLY_APPROVED,
            ],
            status__in=[PlanLineStatus.APPROVED, PlanLineStatus.PARTIALLY_APPROVED],
            approved_headcount__gt=0,
        ).select_related("request_id")
        if not approved_lines.exists():
            raise CampaignServiceError(
                "NO_APPROVED_PLAN_LINE",
                "该计划周期没有已批准的需求行，无法创建招聘项目",
                http_status=422,
            )
        campaign = self.create_campaign(
            code=code,
            title=title,
            campaign_type=campaign_type,
            plan_cycle_id=plan_cycle_id,
            application_open_at=application_open_at,
            application_close_at=application_close_at,
            timezone=timezone,
            description=f"依据 {cycle.year} 年度用人计划创建",
        )
        for line in approved_lines:
            self.create_position(
                campaign_id=str(campaign.id),
                hiring_plan_line_id=str(line.id),
                post_catalog_id=line.post_catalog_id,
                post_catalog_name=line.post_catalog_name,
                organization_id=line.request_id.organization_id,
                organization_name=line.request_id.organization_name,
                planned_headcount=line.approved_headcount,
                min_hires=1,
                max_hires=line.approved_headcount,
                description=line.reason,
            )
        from hr_recruitment.services.audit_service import audit_event

        audit_event(
            tenant_id=self.tenant_id,
            event_type="CAMPAIGN_CREATED_FROM_PLAN",
            business_object="HrRecruitmentCampaign",
            business_object_id=str(campaign.id),
            actor_id=self.actor,
            action="CREATE_FROM_PLAN",
            summary=f"从计划周期创建招聘项目：{title}（岗位 {approved_lines.count()} 个）",
            after={"plan_cycle_id": plan_cycle_id, "position_count": approved_lines.count()},
        )
        return campaign

    # ---- Announcement（公告版本）----

    @transaction.atomic
    def create_announcement(
        self,
        *,
        campaign_id: str,
        title,
        content,
        change_reason="",
    ) -> HrRecruitmentAnnouncementVersion:
        campaign = self._get_campaign(campaign_id)
        last = (
            HrRecruitmentAnnouncementVersion.objects.filter(
                tenant_id=self.tenant_id, campaign_id=campaign
            )
            .order_by("-version_no")
            .first()
        )
        version_no = (last.version_no if last else 0) + 1
        supersedes = last if last and last.immutable_after_publish else None
        return HrRecruitmentAnnouncementVersion.objects.create(
            tenant_id=self.tenant_id,
            campaign_id=campaign,
            version_no=version_no,
            title=title,
            content=content,
            change_reason=change_reason,
            supersedes_id=supersedes,
            effective_at=timezone.now(),
        )

    @transaction.atomic
    def publish_announcement(self, announcement_id: str) -> HrRecruitmentAnnouncementVersion:
        try:
            ann = HrRecruitmentAnnouncementVersion.objects.get(
                id=announcement_id, tenant_id=self.tenant_id
            )
        except HrRecruitmentAnnouncementVersion.DoesNotExist:
            raise CampaignServiceError("ANNOUNCEMENT_NOT_FOUND", "公告不存在", http_status=404)
        if ann.immutable_after_publish and ann.published_at is not None:
            raise CampaignServiceError(
                "ANNOUNCEMENT_ALREADY_PUBLISHED", "公告已发布，不可修改（走 amendment 新建版本）", http_status=409
            )
        ann.published_at = timezone.now()
        ann.save(update_fields=["published_at"])
        return ann

    # ---- Position ----

    @transaction.atomic
    def create_position(
        self,
        *,
        campaign_id: str,
        post_catalog_id=None,
        post_catalog_name="",
        organization_id=None,
        organization_name="",
        hiring_plan_line_id=None,
        position_id=None,
        position_pool_id=None,
        planned_headcount=1,
        min_hires=1,
        max_hires=1,
        description="",
    ) -> HrRecruitmentPosition:
        campaign = self._get_campaign(campaign_id)
        public_slug = slugify(post_catalog_name) or f"pos-{uuid4().hex[:8]}"
        # 同 campaign 内 slug 去重（防同名岗位 slug 冲突，防 public_position 返回错误岗位）
        while HrRecruitmentPosition.objects.filter(
            tenant_id=self.tenant_id, campaign_id=campaign, public_slug=public_slug
        ).exists():
            public_slug = f"{slugify(post_catalog_name) or 'pos'}-{uuid4().hex[:4]}"
        position = HrRecruitmentPosition.objects.create(
            tenant_id=self.tenant_id,
            campaign_id=campaign,
            hiring_plan_line_id=hiring_plan_line_id,
            organization_id=organization_id,
            organization_name=organization_name,
            post_catalog_id=post_catalog_id,
            post_catalog_name=post_catalog_name,
            position_id=position_id,
            position_pool_id=position_pool_id,
            planned_headcount=planned_headcount,
            min_hires=min_hires,
            max_hires=max_hires,
            description=description,
            public_slug=public_slug,
        )
        return position

    def _assert_position(self, position, target: str) -> None:
        allowed = self.POSITION_ALLOWED.get(position.status, set())
        if target not in allowed:
            raise InvalidStateTransitionError(
                f"非法招聘岗位状态迁移: {position.status} -> {target}"
            )

    def _get_position(self, position_id: str, for_update: bool = False) -> HrRecruitmentPosition:
        qs = HrRecruitmentPosition.objects.select_related("campaign_id")
        if for_update:
            qs = qs.select_for_update()
        try:
            return qs.get(id=position_id, tenant_id=self.tenant_id)
        except HrRecruitmentPosition.DoesNotExist:
            raise CampaignServiceError("POSITION_NOT_FOUND", "招聘岗位不存在", http_status=404)

    @transaction.atomic
    def make_ready(self, position_id: str) -> HrRecruitmentPosition:
        """READY：预占 HR02 额度（§9.6）。行锁防与 cancel 并发 TOCTOU；已 READY 幂等返回。"""
        position = self._get_position(position_id, for_update=True)
        self._assert_position(position, RecruitmentPositionStatus.READY)
        if position.position_id is None and position.position_pool_id is None:
            raise CampaignServiceError(
                "POSITION_HR02_REFERENCE_REQUIRED",
                "招聘岗位必须先绑定 HR02 岗位/岗位池才能预占开放",
                http_status=422,
            )
        # 幂等：已 READY 且已有预占 → 直接返回（不重复预占）
        if position.status == RecruitmentPositionStatus.READY and position.reservation_id:
            return position
        provider = Hr02ReservationProvider(tenant_id=self.tenant_id, actor=self.actor)
        idem_key = f"hr04:reserve:{position.id}:{position.version}"
        result = provider.reserve(
            position_id=position.position_id,
            position_pool_id=position.position_pool_id,
            count=position.planned_headcount,
            idempotency_key=idem_key,
            source_business_id=str(position.id),
        )
        position.reserved_headcount = position.planned_headcount
        position.reservation_id = result["reservation_id"]
        position.reservation_no = result["reservation_no"]
        position.status = RecruitmentPositionStatus.READY
        position.version += 1
        position.save(
            update_fields=[
                "reserved_headcount",
                "reservation_id",
                "reservation_no",
                "status",
                "version",
            ]
        )
        return position

    @transaction.atomic
    def open_position(self, position_id: str) -> HrRecruitmentPosition:
        """OPEN：须先发布/开放 campaign（防未开放岗位对公网可见）。"""
        position = self._get_position(position_id, for_update=True)
        self._assert_position(position, RecruitmentPositionStatus.OPEN)
        if position.campaign_id.status not in (
            CampaignStatus.PUBLISHED,
            CampaignStatus.OPEN,
            CampaignStatus.RESULT_PROCESSING,
        ):
            raise CampaignServiceError(
                "CAMPAIGN_NOT_PUBLISHED",
                "招聘项目未发布/未开放，禁止开放岗位报名",
                http_status=409,
            )
        position.status = RecruitmentPositionStatus.OPEN
        position.version += 1
        position.save(update_fields=["status", "version"])
        return position

    @transaction.atomic
    def cancel_position(self, position_id: str, reason: str = "") -> HrRecruitmentPosition:
        """取消：未录用额度必须 release（§9.6）。

        顺序：行锁 → 先写 DB 状态 CANCELLED 并清空预占引用 → 再 release HR02（补偿式）。
        release 失败不阻塞取消（记录到状态字段，由对账/重试补偿），避免"DB 回滚但外部已释放"的悬挂。
        """
        position = self._get_position(position_id, for_update=True)
        self._assert_position(position, RecruitmentPositionStatus.CANCELLED)
        reservation_id = position.reservation_id
        position.reserved_headcount = 0
        position.reservation_id = ""
        position.reservation_no = ""
        position.status = RecruitmentPositionStatus.CANCELLED
        position.version += 1
        position.save(
            update_fields=["reserved_headcount", "reservation_id", "reservation_no", "status", "version"]
        )
        if reservation_id:
            try:
                provider = Hr02ReservationProvider(tenant_id=self.tenant_id, actor=self.actor)
                provider.release(reservation_id)
            except Exception as exc:  # noqa: BLE001
                # 释放失败：状态已取消，预占由 HR02 到期/对账补偿，不阻塞取消
                import logging

                logging.getLogger(__name__).warning(
                    "hr04 cancel release failed reservation=%s reason=%s", reservation_id, exc
                )
        return position
