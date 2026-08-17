"""
hr10_development/tests/test_s3_program.py

S3 培训项目测试。
"""
from django.test import TestCase

from hr10_development.constants import ProgramLifecycleStatus, OfferingStatus
from hr10_development.models.learning_program import HrLearningProgram
from hr10_development.models.offering import HrLearningOffering
from hr10_development.services.offering_service import OfferingService


class ProgramTest(TestCase):
    TENANT_ID = 10001

    def test_create_program(self):
        p = HrLearningProgram.objects.create(
            tenant_id=self.TENANT_ID, program_code="PROG-001", title="新教师培训",
        )
        self.assertEqual(p.lifecycle_status, ProgramLifecycleStatus.DRAFT)

    def test_unique_code_per_tenant(self):
        HrLearningProgram.objects.create(tenant_id=self.TENANT_ID, program_code="PROG-001", title="A")
        from django.db import IntegrityError
        with self.assertRaises(IntegrityError):
            HrLearningProgram.objects.create(tenant_id=self.TENANT_ID, program_code="PROG-001", title="B")


class OfferingTest(TestCase):
    TENANT_ID = 10001

    def setUp(self):
        self.offering = HrLearningOffering.objects.create(
            tenant_id=self.TENANT_ID, program_version_id=1, offering_no="OFF-001",
            delivery_mode="ONSITE", capacity=3, waitlist_capacity=2,
        )

    def test_occupy_seat(self):
        ok = OfferingService.occupy_seat(self.offering)
        self.assertTrue(ok)
        self.offering.refresh_from_db()
        self.assertEqual(self.offering.capacity, 2)

    def test_occupy_last_seat(self):
        for _ in range(3):
            ok = OfferingService.occupy_seat(self.offering)
            self.assertTrue(ok)
        # 第4个失败
        ok = OfferingService.occupy_seat(self.offering)
        self.assertFalse(ok)
