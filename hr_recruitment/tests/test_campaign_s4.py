"""
hr_recruitment/tests/test_campaign_s4.py

HR04-02 招聘项目与岗位（S4）测试：
- Campaign 状态机（DRAFT→UNDER_APPROVAL→APPROVED→PUBLISHED→OPEN→CLOSED→COMPLETED→ARCHIVED）
- Position 状态机 + READY 预占（HR02 HrPositionReservation 真实调用）
- 公告版本 immutable + amendment 新建版本
- 取消岗位释放未录用预占
- HR02 容量 Provider（Hr02CapacityProvider）读取可用额度
"""

from datetime import date, timedelta
from uuid import uuid4

from django.test import TestCase

from hr_structure.models import (
    HrOrganization,
    HrPosition,
    HrPositionPool,
    HrPositionReservation,
    HrPostCatalog,
    HrPostCatalogVersion,
)

from hr_recruitment.api.exceptions import InvalidStateTransitionError
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
from hr_recruitment.services.campaign_service import CampaignService

TENANT = 3001


def make_hr02_position(tenant=TENANT, max_incumbents=2):
    org = HrOrganization.objects.create(
        tenant_id=tenant,
        stable_code=f"ORG-{uuid4().hex[:6]}",
        org_dimension="ADMIN",
    )
    catalog = HrPostCatalog.objects.create(
        tenant_id=tenant, stable_code=f"CAT-{uuid4().hex[:6]}"
    )
    catalog_ver = HrPostCatalogVersion.objects.create(
        catalog_id=catalog,
        tenant_id=tenant,
        name="软件工程专任教师",
        validity_from=date.today(),
    )
    return HrPosition.objects.create(
        tenant_id=tenant,
        position_code=f"POS-{uuid4().hex[:6]}",
        organization_id=org,
        post_catalog_version_id=catalog_ver,
        max_incumbents=max_incumbents,
        validity_from=date.today(),
        lifecycle_status=HrPosition.LifecycleStatus.ACTIVE,
    )


class CampaignServiceTests(TestCase):
    def setUp(self):
        self.service = CampaignService(tenant_id=TENANT, actor="test")
        self.campaign = self.service.create_campaign(
            code="2026-JS-001",
            title="2026 专任教师招聘",
            campaign_type="MULTI_POSITION",
        )
        self.hr_position = make_hr02_position(TENANT, max_incumbents=2)
        self.position = self.service.create_position(
            campaign_id=str(self.campaign.id),
            post_catalog_name="软件工程专任教师",
            organization_name="计算机学院",
            planned_headcount=2,
            min_hires=1,
            max_hires=2,
            position_id=self.hr_position.id,
        )

    def test_campaign_full_state_machine(self):
        self.service.transition_campaign(str(self.campaign.id), target="UNDER_APPROVAL")
        self.service.transition_campaign(str(self.campaign.id), target="APPROVED")
        self.service.transition_campaign(str(self.campaign.id), target="PUBLISHED")
        self.service.transition_campaign(str(self.campaign.id), target="OPEN")
        self.service.transition_campaign(str(self.campaign.id), target="CLOSED")
        self.service.transition_campaign(str(self.campaign.id), target="COMPLETED")
        self.service.transition_campaign(str(self.campaign.id), target="ARCHIVED")
        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.status, CampaignStatus.ARCHIVED)

    def test_campaign_illegal_transition(self):
        with self.assertRaises(InvalidStateTransitionError):
            self.service.transition_campaign(str(self.campaign.id), target="OPEN")

    def test_position_ready_reserves_hr02(self):
        """READY 必须预占 HR02；预占后 HELD。"""
        self.position = self.service.make_ready(str(self.position.id))
        self.assertEqual(self.position.status, RecruitmentPositionStatus.READY)
        self.assertTrue(self.position.reservation_id)
        reservation = HrPositionReservation.objects.get(
            id=int(self.position.reservation_id)
        )
        self.assertEqual(reservation.status, HrPositionReservation.Status.HELD)
        self.assertEqual(reservation.reserved_count, 2)
        self.assertEqual(reservation.source_domain, "hr04")

    def test_position_open_after_ready(self):
        # open 前须发布并开放 campaign（§9.5 防未开放岗位对公网可见）
        self.service.transition_campaign(str(self.campaign.id), target="UNDER_APPROVAL")
        self.service.transition_campaign(str(self.campaign.id), target="APPROVED")
        self.service.transition_campaign(str(self.campaign.id), target="PUBLISHED")
        self.service.transition_campaign(str(self.campaign.id), target="OPEN")
        self.service.make_ready(str(self.position.id))
        self.service.open_position(str(self.position.id))
        self.position.refresh_from_db()
        self.assertEqual(self.position.status, RecruitmentPositionStatus.OPEN)

    def test_position_open_requires_published_campaign(self):
        """未发布 campaign 禁止 open（防未开放岗位对公网可见）。"""
        from hr_recruitment.services.campaign_service import CampaignServiceError

        self.service.make_ready(str(self.position.id))
        with self.assertRaises(CampaignServiceError):
            self.service.open_position(str(self.position.id))

    def test_position_cancel_releases_reservation(self):
        self.service.make_ready(str(self.position.id))
        self.position.refresh_from_db()
        reservation_id = self.position.reservation_id
        self.service.cancel_position(str(self.position.id))
        self.position.refresh_from_db()
        self.assertEqual(self.position.status, RecruitmentPositionStatus.CANCELLED)
        self.assertEqual(self.position.reserved_headcount, 0)
        reservation = HrPositionReservation.objects.get(id=int(reservation_id))
        self.assertEqual(reservation.status, HrPositionReservation.Status.RELEASED)

    def test_make_ready_requires_hr02_reference(self):
        pos = self.service.create_position(
            campaign_id=str(self.campaign.id),
            post_catalog_name="无 HR02 引用岗位",
        )
        from hr_recruitment.services.campaign_service import CampaignServiceError

        with self.assertRaises(CampaignServiceError):
            self.service.make_ready(str(pos.id))


class AnnouncementVersionTests(TestCase):
    def setUp(self):
        self.service = CampaignService(tenant_id=TENANT, actor="test")
        self.campaign = self.service.create_campaign(
            code="2026-ANN-001", title="公告测试", campaign_type="SINGLE_POSITION"
        )

    def test_announcement_versions_increment(self):
        ann1 = self.service.create_announcement(
            campaign_id=str(self.campaign.id), title="公告 v1", content="正文"
        )
        ann2 = self.service.create_announcement(
            campaign_id=str(self.campaign.id),
            title="公告 v2（amendment）",
            content="更正版",
            change_reason="截止日期更正",
        )
        self.assertEqual(ann1.version_no, 1)
        self.assertEqual(ann2.version_no, 2)
        self.assertIsNotNone(ann2.supersedes_id)
        # version unique（DB 约束）
        from django.db import IntegrityError

        with self.assertRaises(IntegrityError):
            HrRecruitmentAnnouncementVersion.objects.create(
                tenant_id=TENANT,
                campaign_id=self.campaign,
                version_no=1,
                title="重复 v1",
            )


class Hr02CapacityProviderTests(TestCase):
    def test_position_capacity_snapshot(self):
        pos = make_hr02_position(TENANT, max_incumbents=3)
        provider = Hr02ReservationProvider(tenant_id=TENANT, actor="test")
        provider.reserve(
            position_id=pos.id, count=1, idempotency_key=f"k-{uuid4().hex[:8]}"
        )
        cap = Hr02CapacityProvider(tenant_id=TENANT).query_capacity(
            tenant_id=TENANT, organization_id=1, position_id=pos.id
        )
        self.assertEqual(cap.status, "OK")
        self.assertEqual(cap.authorized_count, 3)
        self.assertEqual(cap.reserved_count, 1)
        self.assertEqual(cap.available_count, 2)
        self.assertEqual(cap.mode, "HR02_AUTHORITY")

    def test_capacity_unavailable_without_reference(self):
        cap = Hr02CapacityProvider(tenant_id=TENANT).query_capacity(
            tenant_id=TENANT, organization_id=1, position_id=None
        )
        self.assertEqual(cap.status, "UNAVAILABLE")
