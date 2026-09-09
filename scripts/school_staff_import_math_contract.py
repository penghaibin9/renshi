"""Exercise actual decision functions with explicit inputs, never claim ORM proof."""
import ast
import json
import random
import re
import unittest
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
TODAY = date(2026, 9, 6)
SOURCE = ROOT / "backend/hr_staff/services/import_validation.py"
DEFINITIONS = {"ImportRowError", "parse_date", "basic_errors", "_at", "peak_usage", "StructureReferences"}


def enum_values(name):
    tree = ast.parse((ROOT / "backend/hr_staff/constants.py").read_text())
    node = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == name)
    return [ast.literal_eval(item.value.elts[0]) for item in node.body
            if isinstance(item, ast.Assign) and isinstance(item.value, ast.Tuple)]


def validation_functions():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    nodes = [node for node in tree.body if isinstance(node, (ast.ClassDef, ast.FunctionDef))
             and node.name in DEFINITIONS]
    assert {node.name for node in nodes} == DEFINITIONS
    namespace = dict(defaultdict=defaultdict, datetime=datetime, Decimal=Decimal,
                     InvalidOperation=InvalidOperation, re=re,
                     timezone=SimpleNamespace(localdate=lambda: TODAY),
                     normalize_document_number=lambda value: re.sub(r"[\s-]", "", str(value or "")).upper(),
                     StaffCategoryCode=SimpleNamespace(values=enum_values("StaffCategoryCode")),
                     RelationshipType=SimpleNamespace(values=enum_values("RelationshipType")))
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SOURCE), "exec"), namespace)
    return namespace


FUNCTIONS = validation_functions()
RowError = FUNCTIONS["ImportRowError"]


class ImportDecisionTests(unittest.TestCase):
    def setUp(self):
        self.row = dict(staff_no="T001", legal_name="Synthetic Test", effective_from=TODAY.isoformat(),
                        organization_code="OFFICE", position_code="POST-001", fte="1.00")
        cls = FUNCTIONS["StructureReferences"]
        self.refs = cls.__new__(cls)
        self.refs.tenant_id = 1
        org = SimpleNamespace(pk=11, stable_code="OFFICE")
        self.ov = SimpleNamespace(pk=101, status="EFFECTIVE", validity_from=TODAY - timedelta(days=20), validity_to=None)
        self.catalog = SimpleNamespace(pk=301, tenant_id=1, status="ACTIVE",
                                       validity_from=TODAY - timedelta(days=20), validity_to=None)
        self.position = SimpleNamespace(pk=21, position_code="POST-001", lifecycle_status="ACTIVE",
                                        organization_id_id=11, validity_from=TODAY - timedelta(days=20),
                                        validity_to=None, post_catalog_version_id=self.catalog,
                                        planned_fte=Decimal("1"), max_incumbents=1, allow_multiple_incumbents=False)
        self.pv = SimpleNamespace(**{**self.position.__dict__, "pk": 201})
        self.refs.positions = {"post-001": self.position}
        self.refs.organizations = {"office": org}
        self.refs.org_versions = defaultdict(list, {11: [self.ov]})
        self.refs.pos_versions = defaultdict(list, {21: [self.pv]})
        self.refs.intervals = defaultdict(list)
        self.refs.holds = defaultdict(lambda: [0, Decimal("0")])

    def test_valid_row_and_identity_columns(self):
        self.assertEqual(FUNCTIONS["basic_errors"](self.row), {})
        errors = FUNCTIONS["basic_errors"]({**self.row, "legacy_department_id": "7"})
        self.assertIn("legacy_department_id", errors)
        for key in ("staff_no", "organization_code", "position_code"):
            self.assertIn(key, FUNCTIONS["basic_errors"]({**self.row, key: ""}))

    def test_business_day_and_normalized_identity(self):
        tomorrow = TODAY + timedelta(days=1)
        row = {**self.row, "effective_from": tomorrow.isoformat()}
        self.assertNotIn("effective_from", FUNCTIONS["basic_errors"](row, today=tomorrow))
        self.assertIn("effective_from", FUNCTIONS["basic_errors"](row, today=TODAY))
        self.assertIn("document_number", FUNCTIONS["basic_errors"]({**self.row, "document_number": "------"}))

    def test_dates_fte_and_external_workers_are_not_accepted_by_default(self):
        for change, field in (({"fte": "NaN"}, "fte"), ({"fte": "Infinity"}, "fte"),
                              ({"fte": "0.001"}, "fte"), ({"fte": "-1"}, "fte"),
                              ({"effective_from": "not-a-date"}, "effective_from"),
                              ({"effective_from": "2000-01-01", "birth_date": "2001-01-01"}, "effective_from"),
                              ({"effective_from": (TODAY + timedelta(days=1)).isoformat()}, "effective_from"),
                              ({"relationship_type": "EXTERNAL_PART_TIME"}, "relationship_type")):
            with self.subTest(change=change):
                self.assertIn(field, FUNCTIONS["basic_errors"]({**self.row, **change}))

    def test_interval_peak_matches_brute_force_for_300_generated_cases(self):
        rng = random.Random(730629)
        for _ in range(300):
            intervals = []
            for _ in range(rng.randint(0, 20)):
                start = rng.randint(-10, 10)
                finish = rng.randint(start + 1, 15) if rng.random() < .7 else None
                intervals.append((TODAY + timedelta(days=start),
                                  None if finish is None else TODAY + timedelta(days=finish),
                                  Decimal(rng.randint(0, 8)) / 4))
            values = [(sum(start <= day and (end is None or day < end) for start, end, _ in intervals),
                       sum((fte for start, end, fte in intervals if start <= day and (end is None or day < end)), Decimal(0)))
                      for day in (TODAY + timedelta(days=i) for i in range(17))]
            self.assertEqual(FUNCTIONS["peak_usage"](intervals, TODAY),
                             (max(value[0] for value in values), max(value[1] for value in values)))

    def test_half_open_end_does_not_double_count_successor(self):
        tomorrow = TODAY + timedelta(days=1)
        self.assertEqual(FUNCTIONS["peak_usage"]([(TODAY, tomorrow, 1), (tomorrow, None, 1)], TODAY), (1, Decimal("1")))

    def test_reference_snapshot_is_exact_and_preview_without_plan_does_not_reserve(self):
        *_, snapshot = self.refs.resolve(self.row)
        self.assertEqual(snapshot, {"organization": 11, "organizationVersion": 101,
                                    "position": 21, "positionVersion": 201, "catalogVersion": 301})
        self.assertEqual(self.refs.intervals[21], [])
        self.refs.resolve({**self.row, "_structure_snapshot": snapshot})

    def test_unknown_codes_never_select_another_available_object(self):
        for key in ("organization_code", "position_code"):
            with self.subTest(key=key), self.assertRaises(RowError):
                self.refs.resolve({**self.row, key: "FOREIGN"})

    def test_conflicting_organization_versions_fail_closed(self):
        self.refs.org_versions[11].append(self.ov)
        with self.assertRaises(RowError): self.refs.resolve(self.row)

    def test_post_preview_version_change_requires_new_preview(self):
        *_, snapshot = self.refs.resolve(self.row)
        self.pv.pk = 202
        with self.assertRaises(RowError): self.refs.resolve({**self.row, "_structure_snapshot": snapshot})

    def test_frozen_and_mismatched_position_are_rejected(self):
        self.position.lifecycle_status = "FROZEN"
        with self.assertRaises(RowError): self.refs.resolve(self.row)
        self.position.lifecycle_status = "ACTIVE"
        self.position.organization_id_id = 99
        with self.assertRaises(RowError): self.refs.resolve(self.row)

    def test_foreign_catalog_reference_is_rejected(self):
        self.catalog.tenant_id = 2
        with self.assertRaises(RowError): self.refs.resolve(self.row)

    def test_held_or_future_occupancy_blocks_overfill(self):
        self.refs.holds[21] = [1, Decimal(1)]
        with self.assertRaises(RowError): self.refs.resolve(self.row)
        self.refs.holds[21] = [0, Decimal(0)]
        self.refs.intervals[21] = [(TODAY + timedelta(days=5), None, Decimal(1))]
        with self.assertRaises(RowError): self.refs.resolve(self.row)

    def test_file_planning_tracks_both_count_and_fte(self):
        self.pv.max_incumbents = self.position.max_incumbents = 2
        self.pv.allow_multiple_incumbents = self.position.allow_multiple_incumbents = True
        row = {**self.row, "fte": "0.50"}
        self.refs.resolve(row, plan=True)
        self.refs.resolve(row, plan=True)
        with self.assertRaises(RowError): self.refs.resolve(row, plan=True)
        self.assertEqual(len(self.refs.intervals[21]), 2)


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ImportDecisionTests))
    out = ROOT / "tests/artifacts/school-staff-import-offline"
    out.mkdir(parents=True, exist_ok=True)
    (out / "decision-tests.json").write_text(json.dumps({
        "kind": "actual-decision-definitions-with-explicit-input-fixtures-not-orm-not-sql",
        "testsRun": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
        "generatedIntervalCases": 300,
    }, indent=2), encoding="utf-8")
    raise SystemExit(0 if result.wasSuccessful() else 1)
