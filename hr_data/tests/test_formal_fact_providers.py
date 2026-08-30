from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import TestCase

from hr_data.models import AsOfEvidenceSnapshot, PopulationDefinitionVersion
from hr_data.providers.formal_facts import (
    HR13_SPEC,
    hr13_asof_provider,
    hr16_asof_provider,
)
from hr_data.services.asof_service import AsOfReconstructionService


class FormalFactProviderTests(TestCase):
    def _population(self, *, code, root_domain, field, sources):
        return PopulationDefinitionVersion.objects.create(
            tenant_id=77,
            population_code=code,
            name=code,
            root_domain=root_domain,
            predicate_json={"field": field, "op": "eq", "value": "ACTIVE"},
            source_domains=sources,
            version_no=1,
            content_hash="a" * 64,
        )

    @patch("hr_data.providers.formal_facts.apps.get_model", side_effect=LookupError)
    def test_parallel_hr13_app_missing_is_unavailable_not_error(self, _get_model):
        population = self._population(
            code="TITLE_HOLDERS",
            root_domain="HR13",
            field="title.titleCode",
            sources=["HR13"],
        )

        outcome = AsOfReconstructionService(77).reconstruct(
            evidence_no="HR13-NOT-MERGED",
            definition_kind="POPULATION",
            definition_code=population.population_code,
            definition_version=1,
            as_of_date=date(2026, 8, 1),
        )

        self.assertEqual(outcome.evidence.status, AsOfEvidenceSnapshot.Status.UNAVAILABLE)
        self.assertEqual(outcome.evidence.source_statuses_json, {"HR13": "UNAVAILABLE"})
        self.assertEqual(outcome.evidence.blocked_domains_json, ["HR13"])

    @patch("hr_data.providers.formal_facts.apps.get_model")
    def test_hr13_uses_tenant_asof_and_terminal_fact_statuses_when_model_exists(
        self, get_model
    ):
        population = self._population(
            code="TITLE_FACTS",
            root_domain="HR13",
            field="title.titleLevelCode",
            sources=["HR13"],
        )
        model = SimpleNamespace(objects=MagicMock())
        get_model.return_value = model
        initial_qs = MagicMock()
        status_qs = MagicMock()
        ordered_qs = MagicMock()
        values_qs = MagicMock()
        model.objects.filter.return_value = initial_qs
        initial_qs.filter.return_value = status_qs
        status_qs.order_by.return_value = ordered_qs
        ordered_qs.values_list.return_value = values_qs
        values_qs.iterator.return_value = [
            (
                "result-id",
                "R-001",
                "person-id",
                "case-id",
                "PROFESSOR",
                "教授",
                "TEACHING",
                "SENIOR",
                date(2025, 1, 1),
                None,
                "EFFECTIVE",
                None,
            )
        ]

        receipt = hr13_asof_provider(
            tenant_id=77,
            source_domain="HR13",
            definition_kind="POPULATION",
            definition_code=population.population_code,
            definition_version=1,
            as_of_date=date(2026, 8, 1),
        )

        self.assertEqual(receipt["status"], "OK")
        self.assertEqual(receipt["sourceVersion"], HR13_SPEC.provider_version)
        self.assertEqual(len(receipt["evidenceHash"]), 64)
        get_model.assert_called_once_with("hr_title", "ProfessionalTitleResult")
        model.objects.filter.assert_called_once_with(
            tenant_id=77,
            effective_from__lte=date(2026, 8, 1),
        )
        initial_qs.filter.assert_called_once_with(
            status__in=("EFFECTIVE", "REVISED", "REVOKED")
        )
        values_qs.iterator.assert_called_once_with(chunk_size=2000)

    @patch("hr_data.providers.formal_facts.apps.get_model")
    def test_unsupported_hr13_workflow_field_never_queries_fact_model(self, get_model):
        population = self._population(
            code="BAD_TITLE_WORKFLOW",
            root_domain="HR13",
            field="title.reviewScore",
            sources=["HR13"],
        )

        receipt = hr13_asof_provider(
            tenant_id=77,
            source_domain="HR13",
            definition_kind="POPULATION",
            definition_code=population.population_code,
            definition_version=1,
            as_of_date=date(2026, 8, 1),
        )

        self.assertEqual(receipt["status"], "UNAVAILABLE")
        self.assertEqual(receipt["evidenceHash"], "")
        get_model.assert_not_called()

    @patch("hr_data.providers.formal_facts.apps.get_model")
    def test_mutable_retirement_pension_progress_is_not_historical(self, get_model):
        population = self._population(
            code="PENSION_PROGRESS",
            root_domain="HR16",
            field="retirement.pensionProcessingStatus",
            sources=["HR16"],
        )

        receipt = hr16_asof_provider(
            tenant_id=77,
            source_domain="HR16",
            definition_kind="POPULATION",
            definition_code=population.population_code,
            definition_version=1,
            as_of_date=date(2026, 8, 1),
        )

        self.assertEqual(receipt["status"], "UNAVAILABLE")
        self.assertEqual(receipt["evidenceHash"], "")
        get_model.assert_not_called()
