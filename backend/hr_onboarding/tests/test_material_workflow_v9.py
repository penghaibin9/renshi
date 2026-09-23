"""Real DB/file material commands; domain writes and receipts must agree."""
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4
from django.test import TestCase, RequestFactory, override_settings
from django.core.files.uploadedfile import SimpleUploadedFile
from hr_onboarding.tests.test_workflow_v9 import actor, case_fixture, definition
from hr_onboarding.api import materials as api
from hr_onboarding.models import HrOnboardingMaterialRequirement, HrOnboardingMaterial, HrOnboardingAuditEvent, HrMaterialVerification, HrOnboardingIdempotencyRecord
from hr_onboarding.services.material_service import MaterialService
from hr_onboarding.api.exceptions import Hr05ApiError


class MaterialWorkflowV9Tests(TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.settings=override_settings(MEDIA_ROOT=self.tmp.name,MALWARE_SCAN_REQUIRED=False);self.settings.enable();self.addCleanup(self.settings.disable)
        self.user=actor('reviewer',superuser=True);self.case=case_fixture()
        self.req=HrOnboardingMaterialRequirement.objects.create(tenant_id=1,template_version=self.case.template_version,
            material_type='IDENTITY',label='测试身份材料',allowed_formats=['txt'],max_size=1024*1024)
        self.material=HrOnboardingMaterial.objects.create(tenant_id=1,case=self.case,requirement=self.req)
        self.ctx=SimpleNamespace(tenant_id=1,user_id=self.user.id)

    def request(self,view,data=None,*,key=None,fingerprint=None,method='post',material=True):
        req=getattr(RequestFactory(),method)('/',data or {},HTTP_IDEMPOTENCY_KEY=key or uuid4().hex,
                HTTP_IF_MATCH=fingerprint or api.material_fingerprint(self.material))
        req.user=self.user
        with patch.object(api.api_base,'make_hr05_context',return_value=self.ctx):
            if view==api.material_submit:return view(req,self.case.id,self.material.id)
            return view(req,self.material.id if material else self.case.id)

    def upload(self,key='file-one',data=b'synthetic material'):
        return self.request(api.material_submit,{'file':SimpleUploadedFile('one.txt',data,content_type='text/plain')},key=key)

    def test_upload_returns_current_row_and_receipt_without_reloading_others(self):
        res=self.upload();self.assertEqual(res.status_code,200)
        data=json.loads(res.content)['data'];self.material.refresh_from_db()
        self.assertEqual(data['item']['status'],'UNDER_REVIEW');self.assertIn('receipt',data)
        self.assertEqual(HrOnboardingAuditEvent.objects.filter(action='MATERIAL_UPLOAD').count(),1)
        self.assertEqual(len([x for x in Path(self.tmp.name).rglob('*') if x.is_file()]),1)

    def test_same_upload_replay_keeps_same_version_and_file(self):
        first=json.loads(self.upload().content)['data'];version=first['item']['fingerprint']
        second=json.loads(self.upload().content)['data']
        self.assertTrue(second['replayed']);self.assertEqual(first['receipt'],second['receipt']);self.assertEqual(second['item']['fingerprint'],version)
        self.assertEqual(len([x for x in Path(self.tmp.name).rglob('*') if x.is_file()]),1)

    def test_same_key_different_file_rejected(self):
        self.upload();res=self.upload(data=b'another file')
        self.assertEqual(res.status_code,409);self.assertEqual(HrOnboardingAuditEvent.objects.count(),1)

    def test_old_file_review_fingerprint_rejected_after_upload(self):
        self.upload();res=self.request(api.material_verify,{'result':'VERIFIED','reason':'已核对','evidence':'SOURCE-1'})
        self.assertEqual(res.status_code,409);self.assertEqual(HrMaterialVerification.objects.count(),0)

    def test_review_actual_file_and_repeat_is_one_verification(self):
        self.upload();self.material.refresh_from_db();fingerprint=api.material_fingerprint(self.material)
        data={'result':'VERIFIED','reason':'对照原件核验','evidence':'SOURCE-1'}
        first=self.request(api.material_verify,data,key='verify',fingerprint=fingerprint)
        second=self.request(api.material_verify,data,key='verify',fingerprint=fingerprint)
        self.assertEqual(first.status_code,200);self.assertTrue(json.loads(second.content)['data']['replayed'])
        self.assertEqual(HrMaterialVerification.objects.count(),1)
        self.material.refresh_from_db();self.assertEqual(self.material.status,'VERIFIED')

    def test_blank_review_evidence_keeps_pending(self):
        self.upload();self.material.refresh_from_db()
        res=self.request(api.material_verify,{'reason':'核对通过'})
        self.assertGreaterEqual(res.status_code,400);self.material.refresh_from_db();self.assertEqual(self.material.status,'UNDER_REVIEW')

    def test_upload_audit_failure_rolls_back_file_and_row(self):
        with patch.object(HrOnboardingAuditEvent.objects,'create',side_effect=RuntimeError('audit down')):
            with self.assertRaises(RuntimeError):self.upload()
        self.material.refresh_from_db();self.assertEqual(self.material.status,'MISSING')
        self.assertEqual(HrOnboardingIdempotencyRecord.objects.count(),0)
        self.assertFalse(any(x.is_file() for x in Path(self.tmp.name).rglob('*')))

    def test_foreign_tenant_service_cannot_mutate_material(self):
        with self.assertRaises(Hr05ApiError):MaterialService(tenant_id=2).waive_material(self.material,reason='wrong scope')
        self.material.refresh_from_db();self.assertEqual(self.material.status,'MISSING')

    def test_verified_material_cannot_be_returned_to_mutable_state(self):
        self.material.status='VERIFIED';self.material.save()
        with self.assertRaises(Hr05ApiError):MaterialService(tenant_id=1).return_material(self.material,reason='bypass')
        self.material.refresh_from_db();self.assertEqual(self.material.status,'VERIFIED')

    def test_read_never_creates_missing_materials(self):
        self.material.delete()
        res=self.request(api.materials_list,method='get',material=False)
        self.assertEqual(res.status_code,200);self.assertEqual(HrOnboardingMaterial.objects.count(),0)
        self.assertEqual(json.loads(res.content)['data']['missing_requirements'],1)

    def test_explicit_initialization_is_replayable(self):
        self.material.delete()
        first=self.request(api.materials_initialize,material=False,key='initialize',fingerprint=str(self.case.version))
        second=self.request(api.materials_initialize,material=False,key='initialize',fingerprint=str(self.case.version))
        self.assertEqual(first.status_code,200);self.assertTrue(json.loads(second.content)['data']['replayed'])
        self.assertEqual(HrOnboardingMaterial.objects.count(),1)

    def test_cancelled_case_blocks_material_mutation(self):
        self.case.status='CANCELLED';self.case.save()
        res=self.upload();self.assertGreaterEqual(res.status_code,400)
        self.material.refresh_from_db();self.assertEqual(self.material.status,'MISSING')

    def test_illegal_format_cannot_create_file_or_audit(self):
        res=self.request(api.material_submit,{'file':SimpleUploadedFile('one.exe',b'MZ',content_type='application/octet-stream')})
        self.assertGreaterEqual(res.status_code,400);self.assertFalse(any(x.is_file() for x in Path(self.tmp.name).rglob('*')))
        self.assertEqual(HrOnboardingAuditEvent.objects.count(),0)

    def test_optional_waiver_records_reason_not_fake_verification(self):
        self.req.required=False;self.req.save();self.material.refresh_from_db()
        res=self.request(api.material_waive,{'reason':'按本校批准的豁免依据 DOC-42'})
        self.assertEqual(res.status_code,200);self.material.refresh_from_db();self.assertEqual(self.material.status,'WAIVED')
        self.assertEqual(HrOnboardingAuditEvent.objects.get().reason,'按本校批准的豁免依据 DOC-42')
        self.assertEqual(HrMaterialVerification.objects.count(),0)
