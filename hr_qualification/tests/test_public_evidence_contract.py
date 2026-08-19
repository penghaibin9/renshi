"""HR09 public credential evidence contracts."""

from datetime import date, datetime, timezone
from types import SimpleNamespace

from django.test import SimpleTestCase

from hr_qualification.constants import CredentialStatus
from hr_qualification.public import _status_at


class CredentialHistoricalStatusContractTests(SimpleTestCase):
    def test_status_event_chain_restores_pre_renewal_active_state(self):
        credential = SimpleNamespace(
            status=CredentialStatus.SUPERSEDED,
            updated_at=datetime(2026, 8, 10, tzinfo=timezone.utc),
            valid_from=date(2026, 1, 1),
            valid_to=None,
        )
        events = [
            SimpleNamespace(
                to_status=CredentialStatus.ACTIVE,
                occurred_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
            ),
            SimpleNamespace(
                to_status=CredentialStatus.SUPERSEDED,
                occurred_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            ),
        ]

        status = _status_at(
            credential,
            events,
            as_of=date(2026, 6, 30),
            as_of_end=datetime(2026, 7, 1, tzinfo=timezone.utc),
        )

        self.assertEqual(status, CredentialStatus.ACTIVE)

    def test_valid_to_derives_expired_without_mutating_historical_row(self):
        credential = SimpleNamespace(
            status=CredentialStatus.ACTIVE,
            updated_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
            valid_from=date(2026, 1, 1),
            valid_to=date(2026, 5, 1),
        )
        events = [
            SimpleNamespace(
                to_status=CredentialStatus.ACTIVE,
                occurred_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
            )
        ]

        status = _status_at(
            credential,
            events,
            as_of=date(2026, 6, 1),
            as_of_end=datetime(2026, 6, 2, tzinfo=timezone.utc),
        )

        self.assertEqual(status, CredentialStatus.EXPIRED)

    def test_later_projection_without_prior_event_fails_closed(self):
        credential = SimpleNamespace(
            status=CredentialStatus.ACTIVE,
            updated_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            valid_from=None,
            valid_to=None,
        )

        status = _status_at(
            credential,
            [],
            as_of=date(2026, 6, 1),
            as_of_end=datetime(2026, 6, 2, tzinfo=timezone.utc),
        )

        self.assertIsNone(status)
