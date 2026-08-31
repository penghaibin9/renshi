from datetime import date
from unittest.mock import patch

from django.test import TestCase

from hr_staff.constants import CorrectionStatus
from hr_staff.models import HrPerson, HrStaffMaster
from hr_staff.policies import FIELD_GOVERNANCE_REGISTRY
from hr_staff.services.correction_fields import FIELD_CORRECTION_HANDLERS
from hr_staff.services.correction_service import CorrectionService, CorrectionStateError


class CorrectionFieldRegistryTests(TestCase):
    tenant_id = 811

    def setUp(self):
        person = HrPerson.objects.create(
            tenant_id=self.tenant_id,
            legal_name="原姓名",
            birth_date=date(1990, 1, 1),
        )
        self.staff = HrStaffMaster.objects.create(
            tenant_id=self.tenant_id,
            person_id=person,
            staff_no="W1811",
        )
        self.service = CorrectionService(self.tenant_id, actor_user_id=9)

    def _approved_case(self, field_code, new_value, *, evidence=False):
        case = self.service.create_case(
            staff_id=self.staff.id,
            reason="字段注册验收",
            evidence_material_id="11111111-1111-1111-1111-111111111111" if evidence else None,
            items=[
                {
                    "field_code": field_code,
                    "old_value_masked": "old",
                    "new_value_masked": new_value,
                }
            ],
        )
        self.service.submit(case.id)
        self.service.review(case.id)
        return self.service.approve(case.id, approve_high_risk=True)

    def test_every_governed_field_has_explicit_handler(self):
        self.assertEqual(
            set(FIELD_CORRECTION_HANDLERS), set(FIELD_GOVERNANCE_REGISTRY)
        )

    def test_registered_person_fields_apply_without_not_implemented(self):
        case = self._approved_case("person.gender_code", "F")
        self.service.apply(case.id)

        self.staff.person_id.refresh_from_db()
        self.assertEqual(self.staff.person_id.gender_code, "F")

    def test_sensitive_mask_cannot_be_written_as_identity_plaintext(self):
        case = self._approved_case(
            "identity.document_number", "110101********1234", evidence=True
        )
        with self.assertRaises(CorrectionStateError):
            self.service.apply(case.id)

        case.refresh_from_db()
        self.assertEqual(case.status, CorrectionStatus.FAILED)
        self.assertIn("受控密文引用", case.apply_error)
        self.assertNotIn("NotImplementedError", case.apply_error)

    @patch(
        "hr_staff.services.outbox_service.staff_basic_info_corrected",
        side_effect=RuntimeError("outbox unavailable"),
    )
    def test_outbox_failure_rolls_back_authority_and_marks_case_failed(self, _emit):
        case = self._approved_case("person.legal_name", "新姓名")
        with self.assertRaises(CorrectionStateError):
            self.service.apply(case.id)

        self.staff.person_id.refresh_from_db()
        case.refresh_from_db()
        self.assertEqual(self.staff.person_id.legal_name, "原姓名")
        self.assertEqual(case.status, CorrectionStatus.FAILED)
