from importlib import import_module
from types import SimpleNamespace
from unittest import TestCase


class _RecordingQuerySet:
    def __init__(self):
        self.ordered_by = None

    def values(self, *fields):
        return self

    def annotate(self, **annotations):
        return self

    def filter(self, **filters):
        return self

    def order_by(self, *fields):
        self.ordered_by = fields
        return self

    def first(self):
        if self.ordered_by is None:
            raise TypeError("aggregated query must be ordered before first()")
        return None


class ObjectionMigrationRuntimeContractTests(TestCase):
    def test_duplicate_probe_orders_aggregated_queryset_before_first(self):
        migration = import_module(
            "hr_assessment.migrations."
            "0025_hrassessmentobjection_decision_code_and_more"
        )
        queryset = _RecordingQuerySet()
        objection = SimpleNamespace(objects=queryset)
        apps = SimpleNamespace(get_model=lambda *args: objection)

        migration.verify_unique_result_versions(apps, schema_editor=None)

        self.assertEqual(
            queryset.ordered_by,
            ("tenant_id", "result_id", "result_version"),
        )
