import uuid
from datetime import date
from unittest.mock import patch

from django.test import TestCase

from hr_exit.models import RetirementPolicy, RetirementPrecheck
from hr_exit.services.retirement_policy_service import (
    RetirementPolicyError,
    RetirementPolicyService,
    RetirementPrecheckService,
    _add_months,
)
from hr_staff.constants import RelationshipStatus, RelationshipType, StaffCategoryCode
from hr_staff.models import HrEmploymentRelationship, HrPerson, HrStaffMaster


class RetirementPolicyServiceTests(TestCase):
    def setUp(self):
        self.person = HrPerson.objects.create(
            tenant_id=77,
            legal_name="Policy Test Person",
            gender_code="F",
            birth_date=date(1966, 2, 28),
        )
        self.staff = HrStaffMaster.objects.create(
            tenant_id=77,
            person_id=self.person,
            staff_no="RET-001",
            staff_category_code=StaffCategoryCode.TEACHER,
        )
        self.relationship = HrEmploymentRelationship.objects.create(
            tenant_id=77,
            staff_id=self.staff,
            relationship_type=RelationshipType.REGULAR_EMPLOYMENT,
            effective_from=date(1990, 9, 1),
            status=RelationshipStatus.ACTIVE,
        )

    def _draft(self, **overrides):
        payload = {
            "policy_code": "STATUTORY-F-TEACHER",
            "retirement_type": "STATUTORY",
            "gender_code": "F",
            "staff_category_code": StaffCategoryCode.TEACHER,
            "relationship_type": RelationshipType.REGULAR_EMPLOYMENT,
            "retirement_age_months": 720,
            "minimum_service_months": 120,
            "effective_from": date(2026, 1, 1),
            "rationale": "Example statutory policy for test authority evidence.",
        }
        payload.update(overrides)
        return RetirementPolicyService(77, actor_user_id=9).create_draft(**payload)

    @patch("hr_exit.services.retirement_policy_service.emit_registered_event")
    def test_policy_versions_activate_and_active_content_is_immutable(self, emit):
        first = self._draft()
        active = RetirementPolicyService(77, actor_user_id=9).activate(first.id)
        self.assertEqual(active.status, RetirementPolicy.Status.ACTIVE)
        self.assertEqual(len(active.content_hash), 64)
        emit.assert_called_once()

        active.rationale = "silent rewrite"
        with self.assertRaisesMessage(ValueError, "RETIREMENT_POLICY_IMMUTABLE"):
            active.save()

        second = self._draft(retirement_age_months=732)
        self.assertEqual(second.version_no, 2)
        self.assertEqual(second.supersedes_policy_id, first.id)

    @patch("hr_exit.services.retirement_policy_service.emit_registered_event")
    def test_precheck_is_explainable_and_does_not_persist_raw_birth_date(self, _emit):
        policy = self._draft()
        RetirementPolicyService(77).activate(policy.id)

        result = RetirementPrecheckService(77, actor_user_id=9).evaluate(
            person_id=self.person.id,
            employment_relationship_id=self.relationship.id,
            as_of=date(2026, 8, 30),
            idempotency_key="precheck:ret-001:2026-08-30",
        )

        self.assertTrue(result.created)
        self.assertEqual(result.precheck.decision, RetirementPrecheck.Decision.ELIGIBLE)
        self.assertEqual(result.precheck.statutory_date, date(2026, 2, 28))
        self.assertNotIn("birthDate", result.precheck.input_snapshot_json)
        self.assertEqual(result.precheck.explanation_json["reasonCodes"], [])

        replay = RetirementPrecheckService(77).evaluate(
            person_id=self.person.id,
            employment_relationship_id=self.relationship.id,
            as_of=date(2026, 8, 30),
            idempotency_key="precheck:ret-001:2026-08-30",
        )
        self.assertFalse(replay.created)
        self.assertEqual(replay.precheck.id, result.precheck.id)

    @patch("hr_exit.services.retirement_policy_service.emit_registered_event")
    def test_special_policy_requires_condition_and_future_date_is_not_yet(self, _emit):
        policy = self._draft(
            policy_code="SPECIAL-F-TEACHER",
            retirement_age_months=696,
            special_condition_code="HAZARDOUS_DUTY",
            priority=100,
            effective_from=date(2020, 1, 1),
        )
        RetirementPolicyService(77).activate(policy.id)

        no_condition = RetirementPrecheckService(77).evaluate(
            person_id=self.person.id,
            employment_relationship_id=self.relationship.id,
            as_of=date(2023, 1, 1),
            idempotency_key="precheck:no-condition",
        ).precheck
        self.assertEqual(no_condition.decision, RetirementPrecheck.Decision.MANUAL_REVIEW)
        self.assertIn("NO_ACTIVE_POLICY_MATCH", no_condition.explanation_json["reasonCodes"])

        with_condition = RetirementPrecheckService(77).evaluate(
            person_id=self.person.id,
            employment_relationship_id=self.relationship.id,
            as_of=date(2023, 1, 1),
            idempotency_key="precheck:condition",
            special_condition_codes=["hazardous_duty"],
        ).precheck
        self.assertEqual(with_condition.decision, RetirementPrecheck.Decision.NOT_YET)
        self.assertIn("STATUTORY_DATE_NOT_REACHED", with_condition.explanation_json["reasonCodes"])

    def test_cross_tenant_source_is_not_visible(self):
        with self.assertRaises(RetirementPolicyError) as cm:
            RetirementPrecheckService(88).evaluate(
                person_id=self.person.id,
                employment_relationship_id=self.relationship.id,
                as_of=date(2026, 8, 30),
                idempotency_key="precheck:wrong-tenant",
            )
        self.assertEqual(cm.exception.code, "RETIREMENT_PRECHECK_SOURCE_NOT_FOUND")

    def test_month_addition_clamps_end_of_month_deterministically(self):
        self.assertEqual(_add_months(date(1964, 2, 29), 720), date(2024, 2, 29))
        self.assertEqual(_add_months(date(1965, 1, 31), 1), date(1965, 2, 28))
