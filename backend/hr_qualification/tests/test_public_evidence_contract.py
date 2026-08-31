"""HR09 public credential evidence contracts."""

from datetime import date, datetime, timezone
from types import SimpleNamespace

from django.test import SimpleTestCase

from hr_qualification.constants import CredentialStatus, VerificationResult
from hr_qualification.public import _status_at, _verification_at


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

    def test_verification_history_beats_later_current_projection(self):
        credential = SimpleNamespace(
            current_verification_status=VerificationResult.VERIFIED,
            last_verified_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        )
        verifications = [
            SimpleNamespace(
                result=VerificationResult.NEEDS_MANUAL_REVIEW,
                verified_at=datetime(2026, 5, 15, tzinfo=timezone.utc),
            )
        ]

        status, verified_at = _verification_at(
            credential,
            verifications,
            as_of_end=datetime(2026, 7, 1, tzinfo=timezone.utc),
        )

        self.assertEqual(status, VerificationResult.NEEDS_MANUAL_REVIEW)
        self.assertEqual(verified_at, datetime(2026, 5, 15, tzinfo=timezone.utc))

    def test_future_verification_projection_is_not_copied_into_the_past(self):
        credential = SimpleNamespace(
            current_verification_status=VerificationResult.VERIFIED,
            last_verified_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        )

        status, verified_at = _verification_at(
            credential,
            [],
            as_of_end=datetime(2026, 7, 1, tzinfo=timezone.utc),
        )

        self.assertIsNone(status)
        self.assertIsNone(verified_at)
