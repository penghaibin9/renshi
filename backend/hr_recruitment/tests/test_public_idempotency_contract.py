from pathlib import Path

from django.test import RequestFactory, SimpleTestCase

from hr_recruitment.api.base import get_idempotency_key


class PublicRecruitmentIdempotencyContractTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        app_root = Path(__file__).resolve().parents[1]
        cls.public_source = (app_root / "public" / "views.py").read_text(encoding="utf-8")
        cls.service_source = (app_root / "services" / "application_service.py").read_text(
            encoding="utf-8"
        )

    def test_public_apply_requires_mobile_and_idempotency_key(self):
        section = self.public_source[
            self.public_source.index("def public_apply"):
            self.public_source.index("def public_my_applications")
        ]
        self.assertIn('"IDEMPOTENCY_KEY_REQUIRED"', section)
        self.assertIn("not legal_name or not primary_email or not primary_mobile", section)

    def test_idempotency_key_is_bound_to_exact_application(self):
        self.assertIn("recorded.application_id_id != app.id", self.service_source)
        self.assertIn('"IDEMPOTENCY_CONFLICT"', self.service_source)
        self.assertIn("with transaction.atomic():", self.service_source)

    def test_query_string_cannot_supply_idempotency_key(self):
        request = RequestFactory().post(
            "/recruit/example/apply?idempotency_key=leaked"
        )
        self.assertIsNone(get_idempotency_key(request))

    def test_header_and_legacy_form_body_remain_supported(self):
        header_request = RequestFactory().post(
            "/recruit/example/apply",
            headers={"Idempotency-Key": "header-key"},
        )
        form_request = RequestFactory().post(
            "/recruit/example/apply",
            data={"idempotency_key": "form-key"},
        )

        self.assertEqual(get_idempotency_key(header_request), "header-key")
        self.assertEqual(get_idempotency_key(form_request), "form-key")
