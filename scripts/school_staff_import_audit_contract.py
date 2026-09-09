"""Offline verification-rule tests; not a substitute for the MySQL audit seal."""
from copy import deepcopy
import unittest

from school_staff_import_audit import (
    IMPORT_AUDIT_ACTIONS, audit_proof, successful_error_downloads,
)

JOB = "00000000-0000-4000-8000-000000000001"
STAFF = "00000000-0000-4000-8000-000000000002"
PERSON = "00000000-0000-4000-8000-000000000003"
PATH = f"/api/v1/hr/staff/import/{JOB}/errors"


class ImportAuditProofTests(unittest.TestCase):
    def rows(self, downloads=1):
        rows = []
        for action in IMPORT_AUDIT_ACTIONS:
            for _ in range(downloads if action == "StaffImportIssuesDownloaded" else 1):
                row = dict(id=f"event-{len(rows)}", tenant_id=10, actor_user_id=20,
                           action=action, person_id=None, staff_id=None,
                           business_type="", business_id="")
                if action == "PersonCreated":
                    row["person_id"] = PERSON
                if action in {"StaffMasterCreated", "EmploymentRelationshipStarted", "AssignmentCreated",
                              "StaffImportRowCommitted"}:
                    row["staff_id"] = STAFF
                if action in {"StaffImportValidated", "StaffImportCompleted", "StaffImportIssuesDownloaded"}:
                    row.update(business_type="STAFF_IMPORT", business_id=JOB)
                if action in {"EmploymentRelationshipStarted", "AssignmentCreated", "StaffImportRowCommitted"}:
                    row.update(business_type="STAFF_IMPORT" if action == "StaffImportRowCommitted"
                               else "MIGRATION_VERIFIED", business_id=f"import:{JOB}:row:2")
                rows.append(row)
        return rows

    def verify(self, rows, downloads=1):
        return audit_proof(rows, tenant_id=10, actor_id=20, job_id=JOB,
                           staff_id=STAFF, person_id=PERSON,
                           committed_row_no=2, download_accesses=downloads)

    def test_exact_write_chain_and_single_access_pass(self):
        proof = self.verify(self.rows())
        self.assertEqual(proof["status"], "PASS")
        self.assertEqual(proof["auditRows"], 8)

    def test_two_observed_accesses_require_two_distinct_read_audits(self):
        proof = self.verify(self.rows(2), downloads=2)
        self.assertEqual(proof["status"], "PASS")
        self.assertEqual(proof["auditRows"], 9)
        self.assertEqual(proof["mutationEventsExpected"], 7)

    def test_total_count_cannot_hide_missing_action_replaced_by_duplicate(self):
        rows = self.rows()
        rows[0]["action"] = "StaffImportCompleted"
        self.assertEqual(self.verify(rows)["status"], "FAIL")

    def test_any_extra_mutation_fails_even_with_extra_downloads(self):
        rows = self.rows(2)
        extra = deepcopy(rows[1]); extra["id"] = "extra-mutation"; rows.append(extra)
        self.assertEqual(self.verify(rows, downloads=2)["status"], "FAIL")

    def test_unobserved_extra_read_and_missing_read_fail(self):
        self.assertEqual(self.verify(self.rows(2), downloads=1)["status"], "FAIL")
        self.assertEqual(self.verify(self.rows(1), downloads=2)["status"], "FAIL")

    def test_duplicate_event_id_fails(self):
        rows = self.rows(2); rows[-1]["id"] = rows[-2]["id"]
        self.assertEqual(self.verify(rows, downloads=2)["status"], "FAIL")

    def test_wrong_or_missing_actor_and_foreign_tenant_fail(self):
        for field, value in (("actor_user_id", None), ("actor_user_id", 21), ("tenant_id", 11)):
            with self.subTest(field=field, value=value):
                rows = self.rows(); rows[-1][field] = value
                self.assertEqual(self.verify(rows)["status"], "FAIL")

    def test_unrelated_person_staff_job_and_row_audits_fail(self):
        cases = (("PersonCreated", "person_id", "other-person"),
                 ("StaffMasterCreated", "staff_id", "other-staff"),
                 ("StaffImportIssuesDownloaded", "business_id", "other-job"),
                 ("AssignmentCreated", "business_id", f"import:{JOB}:row:3"),
                 ("StaffImportRowCommitted", "business_type", "OTHER"))
        for action, field, value in cases:
            with self.subTest(action=action, field=field):
                rows = self.rows()
                next(row for row in rows if row["action"] == action)[field] = value
                self.assertEqual(self.verify(rows)["status"], "FAIL")

    def test_successful_log_count_ignores_foreign_denials_and_other_endpoints(self):
        log = "\n".join([
            f'INFO django.server [-] "GET {PATH} HTTP/1.1" 200 5333',
            f'INFO django.server [-] "GET {PATH} HTTP/1.0" 200 5333',
            f'WARNING django.server [-] "GET {PATH} HTTP/1.1" 404 300',
            f'WARNING django.server [-] "GET {PATH} HTTP/1.1" 403 400',
            f'INFO django.server [-] "POST {PATH} HTTP/1.1" 200 5333',
            'INFO django.server [-] "GET /api/v1/hr/staff/import/template HTTP/1.1" 200 12417',
            f'INFO django.server [-] "GET {PATH.replace(JOB, STAFF)} HTTP/1.1" 200 5333',
        ])
        self.assertEqual(successful_error_downloads(log, JOB), 2)

    def test_zero_access_and_invalid_job_cannot_pass(self):
        with self.assertRaises(AssertionError):
            successful_error_downloads(f'"GET {PATH} HTTP/1.1" 404 3', JOB)
        with self.assertRaises(ValueError):
            successful_error_downloads("", "not-a-uuid")
        for count in (0, -1, True):
            with self.subTest(count=count), self.assertRaises(AssertionError):
                self.verify(self.rows(), downloads=count)

    def test_diagnostics_do_not_copy_names_documents_or_raw_reason(self):
        rows = self.rows()
        rows[0].update(reason="sensitive fixture reason", document_number="private-document", name="private-name")
        proof = self.verify(rows)
        self.assertNotIn("private-document", str(proof))
        self.assertNotIn("private-name", str(proof))
        self.assertNotIn("sensitive fixture reason", str(proof))


if __name__ == "__main__":
    unittest.main(verbosity=2)
