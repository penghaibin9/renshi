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
        return campaign

    def _get_campaign(self, campaign_id: str) -> HrRecruitmentCampaign:
        try:
            return HrRecruitmentCampaign.objects.get(
                id=campaign_id, tenant_id=self.tenant_id
            )
        except HrRecruitmentCampaign.DoesNotExist:
            raise CampaignServiceError("CAMPAIGN_NOT_FOUND", "招聘项目不存在", http_status=404)

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
            public_slug=slugify(post_catalog_name) or uuid4().hex[:8],
        )
        return position

    def _assert_position(self, position, target: str) -> None:
        allowed = self.POSITION_ALLOWED.get(position.status, set())
        if target not in allowed:
            raise InvalidStateTransitionError(
                f"非法招聘岗位状态迁移: {position.status} -> {target}"
            )

    def _get_position(self, position_id: str) -> HrRecruitmentPosition:
        try:
            return HrRecruitmentPosition.objects.select_related("campaign_id").get(
                id=position_id, tenant_id=self.tenant_id
            )
        except HrRecruitmentPosition.DoesNotExist:
            raise CampaignServiceError("POSITION_NOT_FOUND", "招聘岗位不存在", http_status=404)

    @transaction.atomic
    def make_ready(self, position_id: str) -> HrRecruitmentPosition:
        """READY：预占 HR02 额度（§9.6）。未预占不可进入 READY/OPEN。"""
        position = self._get_position(position_id)
        self._assert_position(position, RecruitmentPositionStatus.READY)
        if position.position_id is None and position.position_pool_id is None:
            # 未绑定 HR02 岗位/岗位池：走容量 Provider 校验后允许（无预占时标记 UNAVAILABLE 会阻断）
            raise CampaignServiceError(
                "POSITION_HR02_REFERENCE_REQUIRED",
                "招聘岗位必须先绑定 HR02 岗位/岗位池才能预占开放",
                http_status=422,
            )
        provider = Hr02ReservationProvider(tenant_id=self.tenant_id, actor=self.actor)
        idem_key = f"hr04:reserve:{position.id}:{position.version}"
        result = provider.reserve(
            position_id=position.position_id,
            position_pool_id=position.position_pool_id,
            count=position.planned_headcount,
            idempotency_key=idem_key,
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
        position = self._get_position(position_id)
        self._assert_position(position, RecruitmentPositionStatus.OPEN)
        position.status = RecruitmentPositionStatus.OPEN
        position.version += 1
        position.save(update_fields=["status", "version"])
        return position

    @transaction.atomic
    def cancel_position(self, position_id: str, reason: str = "") -> HrRecruitmentPosition:
        """取消：未录用额度必须 release（§9.6）。"""
        position = self._get_position(position_id)
        self._assert_position(position, RecruitmentPositionStatus.CANCELLED)
        if getattr(position, "reservation_id", None):
            provider = Hr02ReservationProvider(tenant_id=self.tenant_id, actor=self.actor)
            provider.release(position.reservation_id)
            position.reserved_headcount = 0
        position.status = RecruitmentPositionStatus.CANCELLED
        position.version += 1
        position.save(update_fields=["reserved_headcount", "status", "version"])
        return position
