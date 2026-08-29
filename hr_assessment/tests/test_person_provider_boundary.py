"""HR12 -> HR03 provider boundary contracts."""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch
import uuid

from django.test import SimpleTestCase, TestCase
from django.utils import timezone as django_timezone

from hr_assessment.providers.base import ProviderContext, ProviderStatus
from hr_assessment.providers.interfaces import PersonProvider


class PersonProviderBoundaryTests(SimpleTestCase):
    @patch("hr_staff.public.get_staff_evidence")
    def test_person_provider_uses_source_owned_historical_contract(self, get_evidence):
        staff_id = uuid.uuid4()
        row = SimpleNamespace(
            snapshot=lambda: {
                "staff_id": str(staff_id),
                "person_id": str(uuid.uuid4()),
                "display_name": "Teacher A",
                "worker_category": "TEACHER",
                "status": "ACTIVE",
            }
        )
        get_evidence.return_value = SimpleNamespace(
            rows=(row,),
            missing_staff_ids=(),
            uncertain_identity_staff_ids=(),
        )

        result = PersonProvider().fetch(
            ProviderContext(
                tenant_id=10001,
                ids=[staff_id],
                as_of=datetime(2026, 6, 30, tzinfo=timezone.utc),
            )
        )

        self.assertEqual(result.status, ProviderStatus.OK)
        self.assertEqual(result.data[0]["status"], "ACTIVE")
        get_evidence.assert_called_once_with(
            tenant_id=10001,
            staff_ids=[staff_id],
            as_of=django_timezone.localdate(datetime(2026, 6, 30, tzinfo=timezone.utc)),
            source_version="v1",
        )

    @patch("hr_staff.public.get_staff_evidence")
    def test_aware_as_of_uses_school_local_business_date(self, get_evidence):
        staff_id = uuid.uuid4()
        get_evidence.return_value = SimpleNamespace(
            rows=(),
            missing_staff_ids=(),
            uncertain_identity_staff_ids=(),
        )
        as_of = datetime(2026, 8, 29, 17, 2, tzinfo=timezone.utc)

        PersonProvider().fetch(
            ProviderContext(tenant_id=10001, ids=[staff_id], as_of=as_of)
        )

        get_evidence.assert_called_once_with(
            tenant_id=10001,
            staff_ids=[staff_id],
            as_of=django_timezone.localdate(as_of),
            source_version="v1",
        )

    @patch("hr_staff.public.get_staff_evidence")
    def test_unprovable_historical_identity_is_partial(self, get_evidence):
        staff_id = uuid.uuid4()
        get_evidence.return_value = SimpleNamespace(
            rows=(),
            missing_staff_ids=(),
            uncertain_identity_staff_ids=(staff_id,),
        )

        result = PersonProvider().fetch(
            ProviderContext(tenant_id=10001, ids=[staff_id])
        )

        self.assertEqual(result.status, ProviderStatus.PARTIAL)
        self.assertIn("STAFF_IDENTITY_HISTORY_UNAVAILABLE", result.error_message)


class PersonProviderLocalDateIntegrationTests(TestCase):
    def test_utc_evening_timestamp_keeps_same_school_day_staff_visible(self):
        from hr_staff.models import HrPerson, HrStaffMaster

        boundary = datetime(2026, 8, 29, 17, 2, tzinfo=timezone.utc)
        person = HrPerson.objects.create(
            tenant_id=10001,
            legal_name="本地业务日教师",
            status="ACTIVE",
        )
        staff = HrStaffMaster.objects.create(
            tenant_id=10001,
            person_id=person,
            staff_no="LOCAL-DATE-001",
            current_employment_status="ACTIVE",
        )
        HrPerson.objects.filter(id=person.id).update(created_at=boundary, updated_at=boundary)
        HrStaffMaster.objects.filter(id=staff.id).update(created_at=boundary, updated_at=boundary)

        with django_timezone.override("Asia/Shanghai"):
            result = PersonProvider().fetch(
                ProviderContext(
                    tenant_id=10001,
                    ids=[staff.id],
                    as_of=boundary,
                )
            )

        self.assertEqual(result.status, ProviderStatus.OK)
        self.assertEqual(result.data[0]["display_name"], "本地业务日教师")
