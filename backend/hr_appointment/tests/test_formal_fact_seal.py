import json
import uuid
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import RequestFactory, SimpleTestCase

from hr_appointment import fact_api
from hr_appointment.models import (
    PositionAppointmentFact,
    PositionAppointmentFactQuerySet,
)
from hr_appointment.permissions import (
    FACT_CORRECT_PERMISSION,
    FACT_PUBLISH_PERMISSION,
    FACT_REVOKE_PERMISSION,
)
from hr_appointment.services.fact_authority_service import (
    AppointmentFactAuthorityService,
)


class PositionAppointmentFactSealContractTests(SimpleTestCase):
    def _pending(self):
        return PositionAppointmentFact(
            tenant_id=7,
            appointment_no="APT-SEAL-001",
            person_id=uuid.uuid4(),
            position_instance_id=31,
            application_case_id=uuid.uuid4(),
            effective_from=date(2026, 9, 1),
            idempotency_key="seal-command-001",
        )

    @patch("hr_appointment.decision_models._approved_decision_for_fact", return_value=None)
    def test_seal_builds_verifiable_hash_and_authority_evidence(self, _decision):
        fact = self._pending()
        with patch.object(PositionAppointmentFact, "save", autospec=True) as save:
            fact.seal(
                status=PositionAppointmentFact.Status.EFFECTIVE,
                actor_user_id=88,
                authority_receipt={
                    "permissionCode": FACT_PUBLISH_PERMISSION,
                    "authorityRef": "DECISION-001",
                },
                effect_receipt={"hr03AssignmentId": "ASSIGNMENT-001"},
            )

        save.assert_called_once()
        self.assertTrue(fact.verify_content_hash())
        self.assertEqual(fact.published_by, 88)
        self.assertEqual(fact.authority_receipt_json["authorityRef"], "DECISION-001")

    def test_direct_formal_save_is_rejected_before_database_write(self):
        fact = self._pending()
        fact.status = PositionAppointmentFact.Status.EFFECTIVE
        chain = MagicMock()
        chain.values.return_value.first.return_value = None
        with patch.object(PositionAppointmentFact.objects, "filter", return_value=chain):
            with self.assertRaisesRegex(ValueError, "SERVICE_REQUIRED"):
                fact.save()

    def test_queryset_and_bulk_mutations_are_closed(self):
        queryset = PositionAppointmentFactQuerySet(
            model=PositionAppointmentFact, using="default"
        )
        for operation in (
            lambda: queryset.update(status="REVOKED"),
            queryset.delete,
            lambda: queryset.bulk_create([self._pending()]),
            lambda: queryset.bulk_update([self._pending()], ["status"]),
        ):
            with self.assertRaisesRegex(ValueError, "APPEND_ONLY"):
                operation()

    def test_mysql_migration_contains_update_and_delete_guards(self):
        migration = (
            Path(__file__).resolve().parents[1]
            / "migrations"
            / "0015_formal_appointment_fact_seal.py"
        ).read_text(encoding="utf-8")
        self.assertIn("BEFORE UPDATE ON hr14_position_appointment_fact", migration)
        self.assertIn("BEFORE DELETE ON hr14_position_appointment_fact", migration)
        self.assertIn("SIGNAL SQLSTATE '45000'", migration)
        self.assertIn("OLD.sealed_at IS NOT NULL", migration)


class AppointmentFactAuthorityServiceContractTests(SimpleTestCase):
    def test_correction_appends_successor_with_separate_permission_and_outbox(self):
        source_id = uuid.uuid4()
        source = SimpleNamespace(
            id=source_id,
            person_id=uuid.uuid4(),
            position_instance_id=31,
            application_case_id=uuid.uuid4(),
            reservation_id=51,
            level_code="L7",
            effective_from=date(2026, 9, 1),
            effective_to=None,
            content_hash="a" * 64,
        )
        created = MagicMock(spec=PositionAppointmentFact)
        created.id = uuid.uuid4()
        service = AppointmentFactAuthorityService(7, 88)
        service._replay = MagicMock(return_value=None)
        service._source = MagicMock(return_value=source)

        with (
            patch.object(PositionAppointmentFact.objects, "create", return_value=created) as create,
            patch(
                "hr_appointment.services.fact_authority_service.emit_fact_event"
            ) as emit,
        ):
            result = AppointmentFactAuthorityService.correct.__wrapped__(
                service,
                source_id,
                appointment_no="APT-CORRECT-001",
                idempotency_key="correction-command-001",
                reason="clerical level correction",
                authority_ref="CORRECTION-DECISION-001",
                evidence={"documentRef": "DOC-001"},
                level_code="L8",
            )

        self.assertFalse(result.replayed)
        kwargs = create.call_args.kwargs
        self.assertEqual(kwargs["supersedes_fact_id"], source_id)
        self.assertEqual(kwargs["fact_kind"], PositionAppointmentFact.FactKind.CORRECTION)
        self.assertEqual(kwargs["idempotency_key"], "correction-command-001")
        seal_kwargs = created.seal.call_args.kwargs
        self.assertEqual(seal_kwargs["status"], PositionAppointmentFact.Status.REVISED)
        self.assertEqual(
            seal_kwargs["authority_receipt"]["permissionCode"],
            FACT_CORRECT_PERMISSION,
        )
        emit.assert_called_once()


class AppointmentFactAuthorityApiContractTests(SimpleTestCase):
    class User:
        is_authenticated = True
        is_superuser = False
        id = 88

        def __init__(self, permissions):
            self.permissions = set(permissions)

        def has_perm(self, code):
            return code in self.permissions

    def setUp(self):
        self.factory = RequestFactory()
        self.fact_id = uuid.uuid4()

    @patch("hr_appointment.api.resolve_tenant_from_request", return_value=7)
    @patch("hr_appointment.api.get_allowed_company_ids", return_value={7})
    def test_initial_publish_permission_cannot_correct_or_revoke(self, _allowed, _tenant):
        for endpoint in (fact_api.correct_fact, fact_api.revoke_fact):
            request = self.factory.post(
                "/api/v1/hr/appointments/fact-authority/",
                data=json.dumps({}),
                content_type="application/json",
            )
            request.user = self.User({FACT_PUBLISH_PERMISSION})
            response = endpoint(request, self.fact_id)
            self.assertEqual(response.status_code, 403)

    def test_fact_permissions_are_three_distinct_authorities(self):
        self.assertEqual(
            len({FACT_PUBLISH_PERMISSION, FACT_CORRECT_PERMISSION, FACT_REVOKE_PERMISSION}),
            3,
        )
