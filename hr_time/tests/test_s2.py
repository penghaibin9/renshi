"""
hr_time/tests/test_s2.py

HR11-S2 验收测试：
- 政策包/版本/记录方式模型 + tenant_id NOT NULL（A0 DB 层）
- PUBLISHED 后 immutable guard（内容不可改、只能 RETIRED）
- publish gate + content_hash 冻结 + current_version_id 回写
- Eligibility Resolver：NOT_FOUND / AMBIGUOUS / OK / SOURCE_UNAVAILABLE fail-closed
- 跨租户隔离
"""

from datetime import date

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from hr_time.enums import PolicyStatus, RecordingMethod
from hr_time.models.policy import (
    HrTimePolicyPack,
    HrTimePolicyVersion,
    HrTimeRecordingProfile,
)
from hr_time.providers.base import HrProviderError, PersonRef
from hr_time.services.eligibility import TimePolicyResolver
from hr_time.services.policy_service import PolicyService, PublishGateError

D = date(2026, 1, 1)


def make_profile(tenant_id, code="ADMIN_PROFILE"):
    return HrTimeRecordingProfile.objects.create(
        tenant_id=tenant_id,
        code=code,
        name="行政固定班",
        method=RecordingMethod.FIXED_POSITIVE_TIME,
        effective_from=D,
    )


def make_pack(tenant_id, code="ADMIN_POLICY", scope=None):
    return HrTimePolicyPack.objects.create(
        tenant_id=tenant_id,
        code=code,
        name="行政考勤规则",
        policy_family="ADMIN_FIXED",
        effective_scope=scope or {},
    )


class PolicyModelTests(TestCase):
    def test_tenant_required_fail_closed(self):
        # A0：所有业务表 tenant_id NOT NULL（savepoint 内验证，避免破坏 TestCase 事务）
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                HrTimeRecordingProfile.objects.create(
                    code="NO_TENANT", name="x", method=RecordingMethod.FIXED_POSITIVE_TIME
                )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                HrTimePolicyPack.objects.create(code="NO_TENANT", name="x")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                HrTimePolicyVersion.objects.create(
                    policy_pack=None,
                    version_no=1,
                    status=PolicyStatus.DRAFT,
                    effective_from=D,
                )

    def test_unique_code_per_tenant(self):
        make_profile(1, code="P1")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                make_profile(1, code="P1")
        # 另一租户可复用 code
        make_profile(2, code="P1")

    def test_cross_tenant_isolation(self):
        pack_a = make_pack(1, code="PA")
        pack_b = make_pack(2, code="PB")
        self.assertNotIn(pack_b.id, [p.id for p in HrTimePolicyPack.objects.filter(tenant_id=1)])
        self.assertEqual(HrTimePolicyPack.objects.filter(tenant_id=1).count(), 1)


class PublishFlowTests(TestCase):
    def setUp(self):
        self.profile = make_profile(1)
        self.pack = make_pack(1)
        self.version = HrTimePolicyVersion.objects.create(
            tenant_id=1,
            policy_pack=self.pack,
            version_no=1,
            status=PolicyStatus.DRAFT,
            recording_profile=self.profile,
            grace_policy_json={"late_grace_minutes": 15},
            rounding_policy_json={"rounding": "NONE"},
            effective_from=D,
        )

    def test_publish_freezes_content_hash_and_updates_pack(self):
        PolicyService.publish_version(self.version)
        self.version.refresh_from_db()
        self.pack.refresh_from_db()
        self.assertEqual(self.version.status, PolicyStatus.PUBLISHED)
        self.assertTrue(self.version.content_hash)
        self.assertEqual(self.pack.current_version_id, self.version.id)
        # hash 稳定可复算
        self.assertEqual(self.version.content_hash, self.version.compute_content_hash())

    def test_published_immutable_content(self):
        PolicyService.publish_version(self.version)
        self.version.refresh_from_db()
        self.version.grace_policy_json = {"late_grace_minutes": 30}
        with self.assertRaises(ValidationError):
            self.version.save()
        # 状态改回 DRAFT 也拒绝
        self.version.status = PolicyStatus.DRAFT
        with self.assertRaises(ValidationError):
            self.version.save()

    def test_published_retire_allowed(self):
        PolicyService.publish_version(self.version)
        self.version.refresh_from_db()
        PolicyService.retire_version(self.version)
        self.version.refresh_from_db()
        self.assertEqual(self.version.status, PolicyStatus.RETIRED)

    def test_draft_editable(self):
        self.version.grace_policy_json = {"late_grace_minutes": 5}
        self.version.save()
        self.version.refresh_from_db()
        self.assertEqual(self.version.grace_policy_json["late_grace_minutes"], 5)

    def test_publish_gate_rejects_bad_grace(self):
        self.version.grace_policy_json = {"late_grace_minutes": -1}
        self.version.save()  # draft 可保存
        with self.assertRaises(PublishGateError):
            PolicyService.publish_version(self.version)

    def test_retired_not_publishable(self):
        PolicyService.publish_version(self.version)
        self.version.refresh_from_db()
        PolicyService.retire_version(self.version)
        self.version.refresh_from_db()
        with self.assertRaises(PublishGateError):
            PolicyService.publish_version(self.version)


class FakePersonProvider:
    """# [总控占位] 测试用 PersonProvider 契约实现，HR03 交付后替换为真实实现。"""

    def __init__(self, *, person=None, fail=False):
        self.person = person
        self.fail = fail

    def get_person(self, *, legacy_employee_id, as_of):
        if self.fail:
            raise HrProviderError(code="TIME_SOURCE_UNAVAILABLE", message="HR03 不可用")
        return self.person or PersonRef(legacy_employee_id=legacy_employee_id)

    def get_assignment(self, *, assignment_id, as_of):
        return None

    def health(self):
        from hr_time.providers.base import ProviderHealth

        return ProviderHealth(status="FRESH" if not self.fail else "SOURCE_UNAVAILABLE")


class EligibilityResolverTests(TestCase):
    def test_not_found_when_no_published(self):
        pack = make_pack(1)
        HrTimePolicyVersion.objects.create(
            tenant_id=1, policy_pack=pack, version_no=1,
            status=PolicyStatus.DRAFT, effective_from=D,
        )
        r = TimePolicyResolver(person_provider=FakePersonProvider()).resolve(
            tenant_id=1, staff_master_id=100, as_of=D
        )
        self.assertEqual(r.status, "NOT_FOUND")
        self.assertEqual(r.error_code, "TIME_POLICY_NOT_FOUND")

    def test_tenant_default_match(self):
        profile = make_profile(1)
        pack = make_pack(1)
        v = HrTimePolicyVersion.objects.create(
            tenant_id=1, policy_pack=pack, version_no=1,
            status=PolicyStatus.DRAFT, recording_profile=profile, effective_from=D,
        )
        PolicyService.publish_version(v)
        r = TimePolicyResolver(person_provider=FakePersonProvider()).resolve(
            tenant_id=1, staff_master_id=100, as_of=D
        )
        self.assertEqual(r.status, "OK")
        self.assertEqual(r.policy_version_id, v.id)
        self.assertEqual(r.recording_method, "FIXED_POSITIVE_TIME")
        self.assertEqual(r.resolution_reason, "命中范围: TENANT_DEFAULT")

    def test_ambiguous_fail_closed(self):
        profile = make_profile(1)
        pack = make_pack(1)
        v1 = HrTimePolicyVersion.objects.create(
            tenant_id=1, policy_pack=pack, version_no=1,
            status=PolicyStatus.DRAFT, recording_profile=profile, effective_from=D,
        )
        v2 = HrTimePolicyVersion.objects.create(
            tenant_id=1, policy_pack=pack, version_no=2,
            status=PolicyStatus.DRAFT, recording_profile=profile, effective_from=D,
        )
        PolicyService.publish_version(v1)
        PolicyService.publish_version(v2)
        r = TimePolicyResolver(person_provider=FakePersonProvider()).resolve(
            tenant_id=1, staff_master_id=100, as_of=D
        )
        self.assertEqual(r.status, "AMBIGUOUS")
        self.assertEqual(r.error_code, "TIME_POLICY_AMBIGUOUS")

    def test_source_unavailable_when_provider_fails(self):
        profile = make_profile(1)
        pack = make_pack(1, scope={"type": "WORKER_CATEGORY", "categories": ["teacher"]})
        v = HrTimePolicyVersion.objects.create(
            tenant_id=1, policy_pack=pack, version_no=1,
            status=PolicyStatus.DRAFT, recording_profile=profile, effective_from=D,
        )
        PolicyService.publish_version(v)
        r = TimePolicyResolver(person_provider=FakePersonProvider(fail=True)).resolve(
            tenant_id=1, staff_master_id=100, as_of=D
        )
        self.assertEqual(r.status, "SOURCE_UNAVAILABLE")
        self.assertEqual(r.error_code, "TIME_SOURCE_UNAVAILABLE")

    def test_cross_tenant_no_leak(self):
        profile = make_profile(1)
        pack_a = make_pack(1)
        v = HrTimePolicyVersion.objects.create(
            tenant_id=1, policy_pack=pack_a, version_no=1,
            status=PolicyStatus.DRAFT, recording_profile=profile, effective_from=D,
        )
        PolicyService.publish_version(v)
        r = TimePolicyResolver(person_provider=FakePersonProvider()).resolve(
            tenant_id=2, staff_master_id=100, as_of=D
        )
        self.assertEqual(r.status, "NOT_FOUND")
