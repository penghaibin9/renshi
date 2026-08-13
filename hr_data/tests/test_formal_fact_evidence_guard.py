from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from hr_data.services.evaluation_service import AsOfEvaluationError
from hr_data.services.formal_fact_evidence_guard import verify_formal_fact_evidence


def receipt(hash_value="a" * 64, status="OK"):
    return {
        "status": status,
        "sourceVersion": "formal-v1",
        "evidenceHash": hash_value,
    }


class FormalFactEvidenceGuardTests(SimpleTestCase):
    @staticmethod
    def _result(domain="HR13", frozen_hash="a" * 64):
        return SimpleNamespace(
            definition_kind="POPULATION",
            definition_code="FORMAL_PEOPLE",
            definition_version=1,
            as_of_date=date(2026, 8, 1),
            evidence=SimpleNamespace(
                provider_evidence_hashes_json={domain: frozen_hash},
            ),
        )

    def test_matching_provider_hash_allows_formal_value(self):
        provider = lambda **_kwargs: receipt()
        with patch.dict(
            "hr_data.services.formal_fact_evidence_guard._PROVIDERS",
            {"HR13": provider},
            clear=True,
        ):
            verify_formal_fact_evidence(
                tenant_id=77,
                domain="HR13",
                result=self._result(),
                actor_user_id=9,
            )

    def test_changed_or_missing_provider_hash_rejects_frozen_evidence(self):
        for frozen_hash, current_hash in (("a" * 64, "b" * 64), ("", "a" * 64)):
            provider = lambda **_kwargs: receipt(current_hash)
            with patch.dict(
                "hr_data.services.formal_fact_evidence_guard._PROVIDERS",
                {"HR13": provider},
                clear=True,
            ):
                with self.assertRaises(AsOfEvaluationError) as ctx:
                    verify_formal_fact_evidence(
                        tenant_id=77,
                        domain="HR13",
                        result=self._result(frozen_hash=frozen_hash),
                    )
                self.assertEqual(ctx.exception.code, "ASOF_EVALUATION_EVIDENCE_STALE")

    def test_provider_unavailable_or_wrong_domain_never_returns_a_value(self):
        provider = lambda **_kwargs: receipt("", status="UNAVAILABLE")
        with patch.dict(
            "hr_data.services.formal_fact_evidence_guard._PROVIDERS",
            {"HR14": provider},
            clear=True,
        ):
            with self.assertRaises(AsOfEvaluationError) as ctx:
                verify_formal_fact_evidence(
                    tenant_id=77,
                    domain="HR14",
                    result=self._result(domain="HR14"),
                )
            self.assertEqual(ctx.exception.code, "ASOF_EVALUATION_EVIDENCE_STALE")

        with self.assertRaises(AsOfEvaluationError) as ctx:
            verify_formal_fact_evidence(
                tenant_id=77,
                domain="HR16",
                result=self._result(domain="HR16"),
            )
        self.assertEqual(ctx.exception.code, "ASOF_EVALUATION_SOURCE_UNSUPPORTED")
