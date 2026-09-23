"""V13 regression tests: imported authority readback, not production acceptance."""
from datetime import date
from unittest.mock import patch
from django.test import TestCase
from hr_staff.tests import test_delivery_receipts_v12 as fixture
from hr_staff.models import HrEmploymentRelationship, HrStaffAssignment, HrStaffAuditEvent
from hr_staff.services.import_service import ImportService
from hr_staff.services.import_receipt_service import migration_receipt

class CloseoutReceiptTests(TestCase):
    setUp = fixture.DeliveryReceiptTests.setUp
    writer = staticmethod(fixture.DeliveryReceiptTests.writer)
    commit = fixture.DeliveryReceiptTests.commit
    proof = fixture.DeliveryReceiptTests.proof

    def result(self):
        return ImportService._result_for_job(self.job)

    def test_non_primary_relationship_cannot_be_readback_complete(self):
        self.commit()
        HrStaffAssignment.objects.update(assignment_type="CONCURRENT")
        self.assertFalse(self.result()["readbackComplete"])
        self.assertEqual(self.proof()["verificationStatus"], "NOT_VERIFIED")

    def test_missing_row_audit_is_not_success_on_result_page(self):
        self.commit()
        HrStaffAuditEvent.objects.filter(action="IMPORT_ROW_COMMITTED").delete()
        self.assertFalse(self.result()["readbackComplete"])
        self.assertEqual(self.proof()["verified"], 0)

    def test_duplicate_source_relationship_is_not_success(self):
        self.commit()
        rel=HrEmploymentRelationship.objects.get()
        rel.pk=None
        rel.save()
        self.assertFalse(self.result()["readbackComplete"])
        self.assertFalse(self.proof()["rows"][0]["verified"])

    def test_invalid_committed_row_not_marked_verified(self):
        self.commit()
        self.job.rows.update(is_valid=False)
        self.assertFalse(self.proof()["rows"][0]["verified"])
        self.assertFalse(self.result()["readbackComplete"])

    def test_wrong_failed_counter_is_not_balanced(self):
        self.commit()
        self.job.refresh_from_db()
        self.job.failed_rows=1
        self.job.save(update_fields=["failed_rows"])
        self.assertFalse(self.proof()["accountingBalanced"])
        self.assertFalse(self.result()["readbackComplete"])

    def test_partial_failed_requires_an_actual_failed_row(self):
        self.commit()
        self.job.status="PARTIAL_FAILED"
        self.job.save(update_fields=["status"])
        self.assertEqual(self.proof()["verificationStatus"],"NOT_VERIFIED")

    def test_unrecognized_row_status_is_not_a_completed_error(self):
        self.commit()
        self.job.rows.update(commit_status="LEGACY_UNKNOWN",is_valid=False)
        self.job.status="PARTIAL_FAILED";self.job.failed_rows=1
        self.job.save(update_fields=["status","failed_rows"])
        self.assertFalse(self.proof()["accountingBalanced"])

    def test_explicit_confirmed_history_remains_verified(self):
        self.commit()
        HrEmploymentRelationship.objects.update(status="ENDED",effective_to=date(2026,9,1))
        HrStaffAssignment.objects.update(status="ENDED",effective_to=date(2026,9,1))
        self.assertEqual(self.proof()["verificationStatus"],"VERIFIED")
        self.assertTrue(self.result()["readbackComplete"])

    def test_foreign_organization_cannot_be_proof_of_same_school(self):
        self.commit()
        other=fixture.make_org(222,"FOREIGN","别校",date(2026,1,1))
        HrStaffAssignment.objects.update(organization_id=other)
        self.assertFalse(self.proof()["rows"][0]["verified"])
        self.assertFalse(self.result()["readbackComplete"])

    def test_bound_resource_limit_checked_before_whole_job_is_loaded(self):
        self.commit()
        with patch("hr_staff.services.import_receipt_service.MAX_RECEIPT_ROWS",0):
            with self.assertRaises(ValueError):
                self.proof()

    def test_matching_terminal_and_all_counts_pass(self):
        self.commit()
        r=self.result();p=self.proof()
        self.assertTrue(r["readbackComplete"])
        self.assertEqual(r["readbackCount"],p["verified"])

    def test_resource_limit_is_unknown_not_zero_in_result(self):
        self.commit()
        with patch("hr_staff.services.import_receipt_service.MAX_RECEIPT_ROWS",0):
            r=self.result()
        self.assertIsNone(r["readbackCount"])
        self.assertFalse(r["readbackComplete"])
        self.assertTrue(r["readbackBlocked"])
    def test_bad_checkpoint_blocks_only_summary_verification(self):
        self.commit();self.job.refresh_from_db()
        self.job.checkpoint["committed_rows"]=True;self.job.save(update_fields=["checkpoint"])
        p=self.proof()
        self.assertTrue(p["rows"][0]["verified"])
        self.assertFalse(p["accountingBalanced"])
        self.assertFalse(self.result()["readbackComplete"])
    def test_old_scope_contract_kept_with_explicit_stronger_verification(self):
        self.commit();r=self.result()
        self.assertEqual(r["readbackScope"],"PERSON_STAFF_EMPLOYMENT_ASSIGNMENT")
        self.assertEqual(r["verificationScope"],"PERSON_STAFF_EMPLOYMENT_PRIMARY_ASSIGNMENT_AND_ROW_AUDIT")

    def test_corrupt_checkpoint_is_not_verified(self):
        self.commit();self.job.checkpoint=["invalid"]
        self.job.save(update_fields=["checkpoint"])
        self.assertFalse(self.result()["readbackComplete"])
        self.assertIn("CHECKPOINT_FORMAT_INVALID",self.proof()["accountingIssues"])
    def test_corrupt_committing_checkpoint_does_not_guess_recovery(self):
        self.commit();self.job.checkpoint=["invalid"];self.job.status="COMMITTING"
        self.job.save(update_fields=["checkpoint","status"])
        self.assertFalse(self.result()["resumeAllowed"])
