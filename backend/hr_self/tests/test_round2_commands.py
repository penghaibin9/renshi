from unittest.mock import patch
from django.core.files.storage import default_storage
from django.db import connection, DatabaseError, transaction
from django.test import RequestFactory
from hr_staff.tests.round2_support import MySQLRound2Case
from hr_staff.models import HrMaterialRequest, HrCorrectionCase, HrMaterialSubmission
from hr_staff.services.self_submission_service import SelfCorrectionService, MaterialSubmissionService
from hr_staff.services.correction_service import CorrectionService, CorrectionStateError, CorrectionPolicyDenied
from hr_staff.services.evidence_reference_service import evidence_snapshot, EvidenceReferenceError
from hr_self.command_api import once, endpoint, response
from hr_self.command_contract import CommandError

class SelfCommandsMySQLTests(MySQLRound2Case):
    def setUp(self):
        super().setUp();self.proof=self.evidence();self.self_service=SelfCorrectionService(self.context)
    def correction(self):
        return self.self_service.create_and_submit(reason="Correct my recorded name",
            items=[{"fieldCode":"person.legal_name","newValue":"Corrected fixture staff"}],
            evidence_version_id=self.proof.id)

    def test_upload_by_staff_uuid_keeps_real_file_and_metadata(self):
        self.assertTrue(default_storage.exists(self.proof.storage_file_id))
        self.assertEqual(evidence_snapshot(self.tenant,self.staff.id,self.proof.id)["sha256"],self.proof.sha256)

    def test_actual_file_tampering_is_not_accepted_as_evidence(self):
        with default_storage.open(self.proof.storage_file_id,"wb") as stream:stream.write(b"tampered")
        with self.assertRaises(EvidenceReferenceError):evidence_snapshot(self.tenant,self.staff.id,self.proof.id)

    def test_other_staff_or_tenant_evidence_is_rejected(self):
        import uuid
        for tenant,staff in [(self.tenant+100000,self.staff.id),(self.tenant,uuid.uuid4())]:
            with self.subTest(tenant=tenant,staff=staff),self.assertRaises(EvidenceReferenceError):
                evidence_snapshot(tenant,staff,self.proof.id)

    def test_submission_does_not_change_dossier_until_independent_apply(self):
        case=self.correction();self.assertEqual(case.status,"SUBMITTED")
        self.person.refresh_from_db();self.assertEqual(self.person.legal_name,"Fixture staff")
        manager=CorrectionService(self.tenant,self.reviewer.pk)
        manager.review(case.id);case=manager.approve(case.id)
        manager.apply(case.id,expected_version=case.version)
        self.person.refresh_from_db();self.assertEqual(self.person.legal_name,"Corrected fixture staff")

    def test_self_cannot_approve_own_correction(self):
        case=self.correction();manager=CorrectionService(self.tenant,self.user.pk);manager.review(case.id)
        with self.assertRaises(CorrectionPolicyDenied):manager.approve(case.id)

    def test_changed_source_fails_without_overwriting_new_dossier(self):
        case=self.correction();manager=CorrectionService(self.tenant,self.reviewer.pk)
        manager.review(case.id);manager.approve(case.id)
        self.person.legal_name="Newer authoritative name";self.person.save()
        with self.assertRaises(CorrectionStateError):manager.apply(case.id)
        self.person.refresh_from_db();self.assertEqual(self.person.legal_name,"Newer authoritative name")
        case.refresh_from_db();self.assertEqual(case.status,"FAILED")

    def test_payroll_or_employment_fields_are_not_self_editable(self):
        with self.assertRaises(CommandError):
            self.self_service.create_and_submit(reason="Not permitted",
                items=[{"fieldCode":"employment.effective_from","newValue":"2020-01-01"}],
                evidence_version_id=self.proof.id)
        self.assertEqual(HrCorrectionCase.objects.filter(tenant_id=self.tenant).count(),0)

    def test_supplement_return_reupload_accept_preserves_both_receipts(self):
        request=HrMaterialRequest.objects.create(tenant_id=self.tenant,target_staff_id=self.staff,
            required_category_code="CORRECTION_EVIDENCE",instruction="Supply readable evidence")
        submit=MaterialSubmissionService(self.tenant,self.user.pk)
        review=MaterialSubmissionService(self.tenant,self.reviewer.pk)
        first=submit.submit(request_id=request.id,staff_id=self.staff.id,material_version_id=self.proof.id)
        review.review(submission_id=first.id,action="RETURN",reason="Please add the missing page")
        secondproof=self.evidence("complete second proof")
        second=submit.submit(request_id=request.id,staff_id=self.staff.id,material_version_id=secondproof.id)
        review.review(submission_id=second.id,action="ACCEPT",reason="Verified complete")
        request.refresh_from_db();first.refresh_from_db();second.refresh_from_db()
        self.assertEqual((request.status,first.status,second.status),("VERIFIED","RETURNED","ACCEPTED"))
        self.assertEqual(HrMaterialSubmission.objects.filter(request=request).count(),2)

    def test_idempotent_transport_executes_authority_once(self):
        calls=[]
        def execute():calls.append(1);return {"caseId":"receipt-only"}
        data={"idempotencyKey":"round2-repeat-001"}
        first,created=once(self.context,"fixture",data,execute)
        second,replayed=once(self.context,"fixture",data,execute)
        self.assertEqual(first,second);self.assertTrue(created);self.assertFalse(replayed);self.assertEqual(len(calls),1)
        with self.assertRaises(CommandError):once(self.context,"fixture",{**data,"reason":"changed"},execute)

    def test_missing_signed_page_context_blocks_before_authority_write(self):
        request=RequestFactory().post("/fixture",data="{}",content_type="application/json")
        request.user=self.user;request._dont_enforce_csrf_checks=True  # context test, separate CSRF test follows
        calls=[]
        @endpoint("POST")
        def view(request,context):calls.append(1);return response({"data":{}})
        with patch("hr_self.command_api.resolve_self_context",return_value=self.context):result=view(request)
        self.assertEqual(result.status_code,409);self.assertFalse(calls)

    def test_csrf_is_required_even_with_authenticated_actor(self):
        request=RequestFactory().post("/fixture",data="{}",content_type="application/json");request.user=self.user
        @endpoint("POST")
        def view(request,context):raise AssertionError("Must not reach authority")
        self.assertEqual(view(request).status_code,403)
