from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from hr_data.services.formal_fact_chain_service import FormalFactAsOfEvaluationService
from hr_data.services.formal_fact_evaluation_service import HR13_SPEC, HR14_SPEC


class FormalFactChainTailTests(SimpleTestCase):
    @staticmethod
    def _model_with_chain_count(value):
        model = SimpleNamespace(objects=MagicMock())
        successor_qs = MagicMock(name="successor_qs")
        base_qs = MagicMock(name="base_qs")
        annotated = MagicMock(name="annotated")
        no_successor = MagicMock(name="no_successor")
        active = MagicMock(name="active")
        interval = MagicMock(name="interval")
        predicate = MagicMock(name="predicate")
        values = MagicMock(name="values")
        distinct = MagicMock(name="distinct")

        model.objects.filter.side_effect = [successor_qs, base_qs]
        base_qs.annotate.return_value = annotated
        annotated.filter.return_value = no_successor
        no_successor.filter.return_value = active
        active.filter.return_value = interval
        interval.filter.return_value = predicate
        predicate.values.return_value = values
        values.distinct.return_value = distinct
        distinct.count.return_value = value
        return model, successor_qs, base_qs, distinct

    @patch.object(FormalFactAsOfEvaluationService, "_model")
    def test_hr13_chain_tail_uses_supersedes_result_and_revocation_is_superseding(
        self, model_loader
    ):
        model, _successor_qs, _base_qs, distinct = self._model_with_chain_count(6)
        model_loader.return_value = model
        population = SimpleNamespace(
            predicate_json={"field": "title.titleLevelCode", "op": "eq", "value": "SENIOR"}
        )

        value = FormalFactAsOfEvaluationService(77)._count(
            population,
            HR13_SPEC,
            date(2026, 8, 1),
        )

        self.assertEqual(value, 6)
        successor_kwargs = model.objects.filter.call_args_list[0].kwargs
        self.assertEqual(successor_kwargs["tenant_id"], 77)
        self.assertEqual(successor_kwargs["effective_from__lte"], date(2026, 8, 1))
        self.assertIn("supersedes_result_id", successor_kwargs)
        self.assertEqual(
            successor_kwargs["status__in"],
            ("EFFECTIVE", "REVISED", "REVOKED"),
        )
        distinct.count.assert_called_once_with()

    @patch.object(FormalFactAsOfEvaluationService, "_model")
    def test_hr14_pending_successor_does_not_hide_still_effective_source(self, model_loader):
        model, _successor_qs, _base_qs, distinct = self._model_with_chain_count(4)
        model_loader.return_value = model
        population = SimpleNamespace(
            predicate_json={"field": "appointment.levelCode", "op": "eq", "value": "L7"}
        )

        value = FormalFactAsOfEvaluationService(77)._count(
            population,
            HR14_SPEC,
            date(2026, 8, 1),
        )

        self.assertEqual(value, 4)
        successor_kwargs = model.objects.filter.call_args_list[0].kwargs
        self.assertIn("supersedes_fact_id", successor_kwargs)
        self.assertNotIn("EFFECT_PENDING", successor_kwargs["status__in"])
        self.assertEqual(
            successor_kwargs["status__in"],
            ("EFFECTIVE", "REVISED", "ENDED", "REVOKED"),
        )
        distinct.count.assert_called_once_with()

    @patch.object(FormalFactAsOfEvaluationService, "_model")
    def test_future_successor_is_scoped_out_by_asof_boundary(self, model_loader):
        model, _successor_qs, _base_qs, _distinct = self._model_with_chain_count(2)
        model_loader.return_value = model
        population = SimpleNamespace(
            predicate_json={"field": "title.status", "op": "eq", "value": "EFFECTIVE"}
        )
        clock = date(2025, 12, 31)

        FormalFactAsOfEvaluationService(77)._count(population, HR13_SPEC, clock)

        successor_kwargs = model.objects.filter.call_args_list[0].kwargs
        self.assertEqual(successor_kwargs["effective_from__lte"], clock)
        # A successor whose effective_from is later than this boundary is absent
        # from the EXISTS subquery, so its predecessor remains the historical tail.
