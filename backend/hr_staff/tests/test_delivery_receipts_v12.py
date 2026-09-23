"""P3 controlled ORM proof tests. Not production MySQL/auth acceptance."""
import io
import json
from datetime import date,timedelta
from unittest.mock import patch
from uuid import uuid4
from zipfile import ZipFile
from django.test import TestCase, RequestFactory
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.utils import timezone
from hr_staff.models import (HrPerson,HrStaffMaster,HrEmploymentRelationship,HrStaffAssignment,HrStaffAuditEvent)
from hr_staff.services.import_service import ImportService, ImportStateConflict
from hr_staff.services.import_receipt_service import migration_receipt,receipt_workbook
from hr_staff.services.employment_service import EmploymentService
from hr_staff.services.assignment_service import AssignmentService
from hr_staff.tests.factories import make_org,make_person,make_staff
from hr_staff.context import HrStaffRequestContext,HrStaffScope
from hr_staff.api.imports import import_receipt

class DeliveryReceiptTests(TestCase):
    def setUp(self):
        self.tenant=111;self.svc=ImportService(self.tenant,actor_user_id=77)
        self.org=make_org(self.tenant,"DEPT","测试学院",date(2026,1,1))
        self.job=self.svc.create_job(template_key="staff_master")
        self.svc.parse_rows(self.job,[{"legal_name":"仅数据库保留的测试姓名","staff_no":"T0001","_source_row_no":4}])
        self.svc.validate_rows(self.job,lambda row:{})
        self.writer.produces_staff_master=True
    @staticmethod
    def writer(row,checkpoint):
        # Canonical four-layer services; department-to-HR02 mapping is fixture
        # setup here. Full upload/legacy mapping is tested separately on MySQL.
        src=f"import:{row['_import_job_id']}:row:{row['_import_row_no']}"
        from hr_structure.models import HrOrganization
        person=make_person(111,row["legal_name"]);staff=make_staff(111,person,row["staff_no"])
        rel=EmploymentService(111,77).start_relationship(staff_id=staff,relationship_type="CONTRACT",
            effective_from=date(2026,1,1),source_business_type="MIGRATION_VERIFIED",source_business_id=src)
        AssignmentService(111,audit_actor_user_id=77).create_assignment(employment_relationship_id=rel,assignment_type="PRIMARY",
            effective_from=date(2026,1,1),organization_id=HrOrganization.objects.get(tenant_id=111,stable_code="DEPT"),
            source_business_type="MIGRATION_VERIFIED",source_business_id=src)
        return staff
    def commit(self):
        self.svc.commit(self.job,self.writer)
        return self.proof()
    def proof(self):return migration_receipt(tenant_id=self.tenant,job_id=self.job.id)
    def test_preview_is_not_verified_and_never_creates_authority(self):
        p=self.proof();self.assertEqual(p["pending"],1);self.assertEqual(p["verificationStatus"],"NOT_VERIFIED")
        self.assertEqual(HrStaffMaster.objects.count(),0)
    def test_four_layers_and_same_row_audit_are_required(self):
        p=self.commit();self.assertEqual(p["verificationStatus"],"VERIFIED");self.assertEqual(p["verified"],1)
        self.assertEqual(p["rows"][0]["rowNo"],4)
    def test_no_personal_source_fields_in_receipt(self):
        p=self.commit();text=json.dumps(p,ensure_ascii=False)
        self.assertNotIn("仅数据库保留的测试姓名",text);self.assertNotIn("T0001",text);self.assertNotIn("document_number",text)
    def test_repeat_commit_has_one_staff_one_audit(self):
        self.commit();self.svc.commit(self.job,self.writer)
        self.assertEqual(HrStaffMaster.objects.count(),1)
        self.assertEqual(HrStaffAuditEvent.objects.filter(action="IMPORT_ROW_COMMITTED").count(),1)
    def test_malformed_legacy_receipt_is_readable_not_500(self):
        self.commit();self.job.rows.update(result_ref="invalid-legacy-reference")
        self.assertEqual(self.svc._result_for_job(self.job)["readbackCount"],0)
        self.assertIn("LEGACY_OR_INVALID_RECEIPT",self.proof()["rows"][0]["issues"])
    def test_missing_audit_is_not_verification(self):
        self.commit();HrStaffAuditEvent.objects.filter(action="IMPORT_ROW_COMMITTED").delete()
        self.assertEqual(self.proof()["verified"],0)
        self.assertIn("ROW_AUDIT_MISSING_OR_DUPLICATE",self.proof()["rows"][0]["issues"])
    def test_missing_assignment_is_not_verification(self):
        self.commit();HrStaffAssignment.objects.all().delete()
        self.assertFalse(self.proof()["rows"][0]["authorityComplete"])
    def test_foreign_tenant_row_cannot_be_verified(self):
        self.commit();self.job.rows.update(tenant_id=222)
        self.assertFalse(self.proof()["accountingBalanced"])
        self.assertIn("ROW_TENANT_MISMATCH",self.proof()["rows"][0]["issues"])
    def test_wrong_school_cannot_read_job(self):
        from hr_staff.models import HrImportJob
        with self.assertRaises(HrImportJob.DoesNotExist):migration_receipt(tenant_id=222,job_id=self.job.id)
    def test_wrong_source_relationship_not_silently_accepted(self):
        self.commit();HrEmploymentRelationship.objects.update(source_business_id="unrelated")
        self.assertIn("EMPLOYMENT_SOURCE_MISMATCH",self.proof()["rows"][0]["issues"])
    def test_row_count_mismatch_is_not_complete(self):
        self.commit();self.job.total_rows=2;self.job.save(update_fields=["total_rows"])
        self.assertEqual(self.proof()["verificationStatus"],"NOT_VERIFIED")
    def test_historical_ended_relationship_remains_historical_evidence(self):
        self.commit();HrEmploymentRelationship.objects.update(status="ENDED",effective_to=date(2026,9,1))
        HrStaffAssignment.objects.update(status="ENDED",effective_to=date(2026,9,1))
        self.assertEqual(self.proof()["verificationStatus"],"VERIFIED")
        self.assertIn("历史",self.proof()["limits"][1])
    def test_stale_claim_resumes_but_active_claim_blocks(self):
        self.job.status="COMMITTING";self.job.checkpoint={"commit_token":"first","commit_heartbeat_at":timezone.now().isoformat()};self.job.save()
        with self.assertRaises(ImportStateConflict):self.svc.commit(self.job,self.writer)
        self.job.checkpoint["commit_heartbeat_at"]=(timezone.now()-timedelta(hours=1)).isoformat();self.job.save()
        self.commit();self.assertEqual(HrStaffMaster.objects.count(),1)
    def test_receipt_workbook_is_literal_and_has_all_three_sheets(self):
        raw=receipt_workbook(self.commit(),[(4,"测试",'=HYPERLINK("https://invalid")',"BAD")])
        with ZipFile(io.BytesIO(raw)) as z:
            wb=z.read("xl/workbook.xml").decode();self.assertIn("逐行结果",wb)
            text="".join(z.read(n).decode() for n in z.namelist() if n.startswith("xl/worksheets/"))
            self.assertNotIn("<f>",text);self.assertNotIn("仅数据库保留的测试姓名",text)
            self.assertIn("HYPERLINK",text)
    def test_api_xlsx_records_download_and_no_cache(self):
        self.commit();user=get_user_model().objects.create_user(username="proof-admin",password="test",is_superuser=True)
        req=RequestFactory().get("/receipt?format=xlsx");req.user=user
        ctx=HrStaffRequestContext(tenant_id=111,as_of=date(2026,9,19),scope=HrStaffScope(scope_type="SCHOOL"))
        with patch("hr_staff.api.imports.make_staff_context",return_value=ctx):resp=import_receipt(req,self.job.id)
        self.assertEqual(resp.status_code,200);self.assertEqual(resp["Cache-Control"],"no-store")
        self.assertEqual(resp.content[:2],b"PK");self.assertTrue(HrStaffAuditEvent.objects.filter(action="IMPORT_RECEIPT_DOWNLOAD").exists())
    def test_api_requires_import_permission(self):
        req=RequestFactory().get("/receipt");req.user=get_user_model().objects.create_user(username="no-proof-perm",password="test")
        with self.assertRaises(PermissionDenied):import_receipt(req,self.job.id)
    def test_api_college_scope_is_refused(self):
        req=RequestFactory().get("/receipt");req.user=get_user_model().objects.create_user(username="college-proof",password="test",is_superuser=True)
        ctx=HrStaffRequestContext(tenant_id=111,as_of=date(2026,9,19),scope=HrStaffScope(scope_type="COLLEGE"))
        with patch("hr_staff.api.imports.make_staff_context",return_value=ctx):resp=import_receipt(req,self.job.id)
        self.assertEqual(resp.status_code,403)
    def test_failure_of_fourth_layer_leaves_no_half_person(self):
        with patch("hr_staff.services.assignment_service.AssignmentService.create_assignment",side_effect=ValueError("injected")):
            result=self.svc.commit(self.job,self.writer)
        self.assertEqual(result["committed"],0)
        for model in (HrPerson,HrStaffMaster,HrEmploymentRelationship,HrStaffAssignment):self.assertEqual(model.objects.count(),0)
        self.assertEqual(self.proof()["failed"],1)

    def test_historical_free_text_is_not_exported_in_receipt(self):
        from hr_staff.models import HrImportIssue
        HrImportIssue.objects.create(tenant_id=self.tenant,job_id=self.job,row_no=4,field_code='legal_name',
            error_code='LEGACY_UNKNOWN',message='SECRET-NAME-AND-ID')
        payload=self.proof()
        self.assertNotIn('SECRET-NAME-AND-ID',json.dumps(payload,ensure_ascii=False))
        self.assertEqual(payload['errorRows'][0][1],'姓名')
