"""Executable R11→HR invariants, SQLite ORM plus actual views; not MySQL/SSO proof."""
from __future__ import annotations
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch
import uuid

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db import models, connection, DatabaseError, transaction
from django.test import TestCase, RequestFactory, override_settings
from django.utils import timezone
from hr_assessment.models import (HrAssessmentCase, HrSubjectSnapshot, HrAssessmentCycle,
    HrCycleSnapshot, HrProviderSnapshotSet, HrProviderSnapshotItem,
    HrFinalAssessmentResult, HrResultNotice, HrAcknowledgement, HrAssessmentArchivePackage,
    HrAssessmentArchiveAccessAudit, HrAssessmentDocument)
from hr_assessment.services.archive_evidence import (freeze_result_context, verified_archive,
    archive_projection, ArchiveEvidenceError, digest, credential_attachment_index)
from hr_assessment.services.result_lifecycle_service import AssessmentResultLifecycleService, AssessmentResultLifecycleError
from hr_assessment.services.result_correction_service import AssessmentResultCorrectionService, ResultCorrectionInput
from hr_assessment.services.document_service import open_verified_document, AssessmentDocumentError
from hr_assessment.api import views_archive

TENANT = 77


def make_case(*, tenant=TENANT, name='证据样本教师', score=Decimal('88.50'), legacy=False, staff_id=None, credential_payload=None):
    now=timezone.now(); policy=uuid.uuid4(); staff=staff_id or uuid.uuid4()
    cycle=HrAssessmentCycle.objects.create(tenant_id=tenant, cycle_no=str(uuid.uuid4()),name='2026年度考核',assessment_type='ANNUAL',start_at=now.replace(month=1,day=1),end_at=now.replace(month=12,day=31),policy_version_id=policy)
    case=HrAssessmentCase.objects.create(tenant_id=tenant, assessment_type='ANNUAL', cycle=cycle,staff_id=staff,policy_version_id=policy,status='FINALIZED')
    subject=HrSubjectSnapshot.objects.create(tenant_id=tenant,case_id=case.id,staff_id=staff,display_name=name,staff_code='T001',org_name='工程学院',position_name='专任教师',snapshot_at=now)
    case.subject_snapshot=subject
    cycle_snap=HrCycleSnapshot.objects.create(tenant_id=tenant,cycle=cycle,frozen_at=now,frozen_policy_json={'title':'原制度'},frozen_indicator_set_json={'rule':'原指标'})
    document_id,credential_id=uuid.uuid4(),uuid.uuid4()
    payload={'credential_id':str(credential_id),'staff_id':str(staff),'credential_name':'教学资格','document_refs':['hr09-private-ref'],
      'document_snapshots':[{'documentId':str(document_id),'credentialId':str(credential_id),'fileRef':'hr09-private-ref','version':2,'sha256':'a'*64,'documentType':'CERTIFICATE','uploadedAt':now.isoformat(),'verifiedAtCapture':True,'bytesVerified':False}]}
    if credential_payload is not None:payload=credential_payload
    snap=HrProviderSnapshotSet.objects.create(tenant_id=tenant,case_id=case.id,as_of=now,authority_json={'policyVersionId':str(policy)},required_providers_json=['qualification'],provider_status_json={'qualification':{'status':'OK'}},content_hash=digest({'test-source-envelope':payload}),status='CAPTURING')
    item=HrProviderSnapshotItem.objects.create(tenant_id=tenant,snapshot_set=snap,case_id=case.id,provider_type='qualification',source_object_type='HrCredential',source_object_id=str(credential_id),source_version='hr09-credential-evidence-v1',source_as_of=now,trust_level='SOURCE_VERIFIED',snapshot_json=payload,status='VERIFIED')
    snap.seal_capture(status='READY'); case.provider_snapshot_set_id=snap.id;case.save()
    calc={'source':'SERVER_POLICY','scoreAggregation':'AVERAGE','policyVersionId':str(policy),'resultRuleVersionId':str(uuid.uuid4()),'contributions':[]}
    if not legacy:calc.update(providerSnapshotSetId=str(snap.id),evidenceBinding=freeze_result_context(case))
    result=HrFinalAssessmentResult.objects.create(tenant_id=tenant,case_id=case.id,assessment_type='ANNUAL',cycle_id=cycle.id,grade_code='QUALIFIED',display_grade_snapshot_json={'zh-CN':'合格'},calculated_score=score,calculation_snapshot_json=calc,policy_version_id=policy,decision_reason='已复核',finalized_at=now)
    return SimpleNamespace(case=case,subject=subject,cycle=cycle,cycle_snap=cycle_snap,snapshot=snap,item=item,result=result,staff=staff)


def allow_archive(result, version=1):
    now=timezone.now()
    HrResultNotice.objects.create(tenant_id=result.tenant_id,result=result,result_version=version,notice_no=str(uuid.uuid4()),delivery_status='DELIVERED',delivery_receipt_ref='test-real-orm-receipt',delivered_at=now)
    HrAcknowledgement.objects.create(tenant_id=result.tenant_id,result=result,result_version=version,acknowledgement_status='RECEIVED_AGREE',confirmed_at=now)


def archive_case(context):
    allow_archive(context.result)
    return AssessmentResultLifecycleService(context.result.tenant_id).archive(result_id=context.result.id)


class FrozenArchiveTests(TestCase):
    def setUp(self):
        self.ctx=make_case();self.a=archive_case(self.ctx)

    def test_complete_archive_is_v2_and_hash_verifies(self):
        p=verified_archive(self.a)
        self.assertEqual(p['schemaVersion'],'hr12-archive-v2')
        self.assertEqual(p['evidence']['subject']['display_name'],'证据样本教师')
        self.assertEqual(p['canonicalResult']['calculatedScore'],'88.50')

    def test_current_identity_and_cycle_edits_do_not_rewrite_history(self):
        HrSubjectSnapshot.objects.filter(pk=self.ctx.subject.pk).update(display_name='今天新姓名',org_name='今天新学院')
        HrAssessmentCycle.objects.filter(pk=self.ctx.cycle.pk).update(name='新周期名')
        HrCycleSnapshot.objects.filter(pk=self.ctx.cycle_snap.pk).update(frozen_policy_json={'new':True})
        actual=archive_projection(HrAssessmentArchivePackage.objects.get(pk=self.a.pk))
        self.assertEqual(actual['subject']['display_name'],'证据样本教师')
        self.assertEqual(actual['cycle']['nameAtFinalization'],'2026年度考核')
        self.assertNotIn('今天新',json.dumps(actual,ensure_ascii=False))

    def test_change_before_archiving_uses_finalization_not_current_context(self):
        c=make_case();c.subject.display_name='后改姓名';c.subject.save()
        c.cycle_snap.frozen_policy_json={'later':True};c.cycle_snap.save()
        a=archive_case(c)
        self.assertEqual(a.manifest_json['evidence']['subject']['display_name'],'证据样本教师')
        self.assertEqual(a.manifest_json['evidence']['cycle']['snapshot']['frozen_policy_json'],{'title':'原制度'})

    def test_no_live_source_dependency_when_reading(self):
        with patch('hr_qualification.public.get_formal_credential_evidence',side_effect=AssertionError('no live data')), patch.object(HrSubjectSnapshot.objects,'filter',side_effect=AssertionError('no current identity')):
            self.assertEqual(archive_projection(self.a)['attachments'][0]['version'],2)

    def test_projection_is_detached_from_persisted_json(self):
        p=archive_projection(self.a);p['subject']['display_name']='mutated'
        self.assertEqual(archive_projection(self.a)['subject']['display_name'],'证据样本教师')

    def test_legacy_v1_explicitly_has_no_frozen_identity(self):
        old=archive_case(make_case(legacy=True))
        p=archive_projection(old)
        self.assertFalse(p['identityFrozen']);self.assertNotIn('subject',p)
        self.assertIn('不使用当前',p['identityNote'])

    def test_source_file_metadata_is_not_claimed_as_bytes_verified(self):
        p=archive_projection(self.a)
        self.assertEqual(p['attachments'][0]['verificationStatus'],'METADATA_FROZEN_BYTES_NOT_CHECKED')
        self.assertNotIn('fileRef',p['attachments'][0])
        self.assertNotIn('hr09-private-ref',json.dumps(p))

    def test_hash_tampering_refused(self):
        self.a.manifest_json['canonicalResult']['gradeCode']='EXCELLENT'
        with self.assertRaises(ArchiveEvidenceError):verified_archive(self.a)

    def test_rehash_outer_manifest_does_not_allow_changed_frozen_identity(self):
        self.a.manifest_json['evidence']['subject']['display_name']='伪造姓名'
        self.a.content_hash=digest(self.a.manifest_json);self.a.archive_provider_ref='hr12://archive/'+self.a.content_hash
        with self.assertRaisesRegex(ArchiveEvidenceError,'审定时'):verified_archive(self.a)

    def test_mismatched_archive_school_refused(self):
        self.a.tenant_id=88
        with self.assertRaises(ArchiveEvidenceError):verified_archive(self.a)

    def test_missing_seal_refused(self):
        self.a.sealed_at=None
        with self.assertRaises(ArchiveEvidenceError):verified_archive(self.a)

    def test_unknown_schema_refused(self):
        self.a.manifest_json['schemaVersion']='invented'
        self.a.content_hash=digest(self.a.manifest_json);self.a.archive_provider_ref='hr12://archive/'+self.a.content_hash
        with self.assertRaises(ArchiveEvidenceError):verified_archive(self.a)

    def test_instance_update_and_delete_refused(self):
        with self.assertRaisesRegex(ValueError,'IMMUTABLE'):self.a.save()
        with self.assertRaisesRegex(ValueError,'IMMUTABLE'):self.a.delete()

    def test_stale_instance_cannot_downgrade_then_modify(self):
        self.a.archive_status='PENDING'
        with self.assertRaisesRegex(ValueError,'IMMUTABLE'):self.a.save()

    def test_queryset_update_delete_and_bulk_rejected(self):
        q=HrAssessmentArchivePackage.objects.filter(pk=self.a.id)
        with self.assertRaisesRegex(ValueError,'IMMUTABLE'):q.update(manifest_json={})
        with self.assertRaisesRegex(ValueError,'IMMUTABLE'):q.delete()
        with self.assertRaises(ValueError):q.bulk_update([self.a],['manifest_json'])
        with self.assertRaises(ValueError):q.bulk_create([self.a])

    def test_same_archive_request_is_idempotent(self):
        a2=AssessmentResultLifecycleService(TENANT).archive(result_id=self.ctx.result.id)
        self.assertEqual(a2.id,self.a.id);self.assertEqual(HrAssessmentArchivePackage.objects.count(),1)

    def test_replay_with_different_refs_rejected(self):
        with self.assertRaisesRegex(AssessmentResultLifecycleError,'引用不一致'):
            AssessmentResultLifecycleService(TENANT).archive(result_id=self.ctx.result.id,document_refs=['different'])

    def test_notice_and_ack_still_required(self):
        c=make_case()
        with self.assertRaises(AssessmentResultLifecycleError):AssessmentResultLifecycleService(TENANT).archive(result_id=c.result.id)
        self.assertFalse(HrAssessmentArchivePackage.objects.filter(result=c.result).exists())

    def test_bad_source_hash_blocks_new_finalization_binding(self):
        # Direct SQL-like bypass only to inject corruption, not the product write path.
        models.QuerySet.update(HrProviderSnapshotItem.objects.filter(pk=self.ctx.item.pk),snapshot_json={'tampered':True})
        with self.assertRaises(ArchiveEvidenceError):freeze_result_context(self.ctx.case)
        # Existing result keeps its immutable snapshot, independent of later corruption.
        self.assertEqual(archive_projection(self.a)['result']['calculatedScore'],'88.50')

    def test_incomplete_legacy_context_does_not_get_fabricated_details(self):
        self.ctx.case.provider_snapshot_set_id=None
        self.assertEqual(freeze_result_context(self.ctx.case)['status'],'NOT_CAPTURED')

    def test_bad_subject_staff_mismatch_blocks_binding(self):
        self.ctx.subject.staff_id=uuid.uuid4();self.ctx.subject.save()
        with self.assertRaises(ArchiveEvidenceError):freeze_result_context(self.ctx.case)

    def test_formal_correction_keeps_old_archive_version(self):
        AssessmentResultCorrectionService(TENANT,actor_staff_id=uuid.uuid4()).append(
            result_id=self.ctx.result.id,payload=ResultCorrectionInput(correction_no='C1',expected_version=1,revision_type='CORRECTION',reason='授权更正依据',changes={'calculatedScore':'90.00'}))
        self.ctx.result.refresh_from_db()
        self.assertEqual(archive_projection(self.a)['result']['calculatedScore'],'88.50')
        allow_archive(self.ctx.result,2)
        new=AssessmentResultLifecycleService(TENANT).archive(result_id=self.ctx.result.id)
        self.assertEqual(new.result_version,2)
        self.assertEqual(archive_projection(new)['result']['calculatedScore'],'90.00')
        self.assertEqual(archive_projection(new)['resultBasis'],'CORRECTION_WITH_ORIGINAL_EVIDENCE')

    def test_attachment_duplicate_conflict_and_wrong_owner_rejected(self):
        items=copy.deepcopy(self.a.manifest_json['evidence']['providerItems'])
        items[0]['snapshot']['document_snapshots'].append({**items[0]['snapshot']['document_snapshots'][0],'version':3})
        with self.assertRaises(ArchiveEvidenceError):credential_attachment_index(items,self.ctx.staff)
        with self.assertRaises(ArchiveEvidenceError):credential_attachment_index(self.a.manifest_json['evidence']['providerItems'],uuid.uuid4())

    def test_missing_historical_doc_checksum_is_reported(self):
        items=copy.deepcopy(self.a.manifest_json['evidence']['providerItems']);items[0]['snapshot']['document_snapshots'][0]['sha256']=''
        docs,gaps=credential_attachment_index(items,self.ctx.staff)
        self.assertEqual(docs[0]['verificationStatus'],'CHECKSUM_NOT_CAPTURED')

    def test_legacy_refs_get_gap_not_today_document_query(self):
        items=copy.deepcopy(self.a.manifest_json['evidence']['providerItems']);items[0]['snapshot'].pop('document_snapshots')
        docs,gaps=credential_attachment_index(items,self.ctx.staff)
        self.assertEqual(docs,[]);self.assertEqual(gaps[0]['status'],'LEGACY_REFERENCES_ONLY')


class ArchiveHttpTests(TestCase):
    def setUp(self):
        self.ctx=make_case(name='=HYPERLINK("https://invalid","person")');self.a=archive_case(self.ctx)
        self.user=get_user_model().objects.create_user(username='archive-reader',password='test-pass')
        self.rf=RequestFactory()
        self.user.has_perm=lambda code:code in getattr(self,'perms',{'hr.assessment.archive_manager'})
        # Explicit membership fixture only; actual decorators and staff lookup execute.
        self.allowed=patch('base.auth_backends.get_allowed_company_ids',return_value=[TENANT]);self.allowed.start();self.addCleanup(self.allowed.stop)

    def req(self, method='get', body=None, tenant=TENANT, purpose='年度档案核查'):
        request=getattr(self.rf,method)('/',data=json.dumps(body),content_type='application/json') if method=='post' else self.rf.get('/')
        request.user=self.user;request.tenant_id=tenant
        if purpose is not None:request.META['HTTP_X_HR_ACCESS_REASON']=purpose
        return request

    def read(self, req=None, version=1):
        return views_archive.evidence(req or self.req(),self.ctx.result.id,version)

    def test_get_returns_frozen_values_and_appends_audit(self):
        response=self.read();self.assertEqual(response.status_code,200)
        self.assertIn('no-store',response['Cache-Control'])
        audit=HrAssessmentArchiveAccessAudit.objects.get();self.assertEqual(audit.actor_user_id,self.user.pk);self.assertEqual(audit.action,'VIEW')

    def test_anonymous_user_refused(self):
        from django.contrib.auth.models import AnonymousUser
        req=self.req();req.user=AnonymousUser()
        with self.assertRaises(PermissionDenied):self.read(req)

    def test_missing_permission_refused(self):
        self.perms=set()
        with self.assertRaises(PermissionDenied):self.read()

    def test_current_membership_revocation_refused(self):
        with patch('base.auth_backends.get_allowed_company_ids',return_value=[]):self.assertEqual(self.read().status_code,403)

    def test_cross_tenant_context_and_object_refused(self):
        self.assertEqual(self.read(self.req(tenant=88)).status_code,403)
        other=archive_case(make_case(tenant=88))
        self.assertEqual(views_archive.evidence(self.req(),other.result_id,1).status_code,404)

    def test_reason_required_length_and_control_chars(self):
        for purpose in (None,'',' '*4,'x'*501,'a\nb'):
            with self.subTest(purpose=repr(purpose)[:30]):self.assertEqual(self.read(self.req(purpose=purpose)).status_code,400)
        self.assertEqual(HrAssessmentArchiveAccessAudit.objects.count(),0)

    def test_unknown_version_returns_404_and_no_audit(self):
        self.assertEqual(self.read(version=5).status_code,404)
        self.assertEqual(HrAssessmentArchiveAccessAudit.objects.count(),0)

    def test_audit_failure_withholds_response(self):
        with patch.object(HrAssessmentArchiveAccessAudit.objects,'create',side_effect=DatabaseError('storage fail')):
            response=self.read();self.assertEqual(response.status_code,503);self.assertNotIn('HYPERLINK',response.content.decode())

    def test_corrupt_manifest_withholds_response(self):
        models.QuerySet.update(HrAssessmentArchivePackage.objects.filter(pk=self.a.pk),content_hash='b'*64)
        self.assertEqual(self.read().status_code,409)
        self.assertEqual(HrAssessmentArchiveAccessAudit.objects.count(),0)

    def test_export_is_separate_permission(self):
        with self.assertRaises(PermissionDenied):views_archive.export_evidence(self.req(),self.ctx.result.id,1)

    def test_export_actual_xlsx_has_five_sheets_and_text_not_formula(self):
        from openpyxl import load_workbook
        self.perms={'hr.assessment.archive.export'}
        response=views_archive.export_evidence(self.req(),self.ctx.result.id,1)
        self.assertEqual(response.status_code,200)
        wb=load_workbook(io.BytesIO(response.content));self.assertEqual(len(wb.worksheets),5)
        names=[c.value for row in wb['归档说明'] for c in row]
        self.assertTrue(any(str(v).startswith("'=HYPERLINK") for v in names))
        self.assertFalse(any(c.data_type=='f' for sheet in wb for row in sheet for c in row))
        self.assertEqual(HrAssessmentArchiveAccessAudit.objects.get().action,'EXPORT')

    def test_compare_match_is_single_sample_and_does_not_modify_result(self):
        body={'sampleRef':'人工表第7行','expectedScore':'88.50','expectedGrade':'QUALIFIED'}
        response=views_archive.compare_evidence(self.req('post',body),self.ctx.result.id,1)
        self.assertEqual(response.status_code,200);self.assertEqual(json.loads(response.content)['data']['status'],'MATCH')
        self.ctx.result.refresh_from_db();self.assertEqual(self.ctx.result.calculated_score,Decimal('88.50'))
        self.assertEqual(self.ctx.result.revisions.count(),0)
        audit=HrAssessmentArchiveAccessAudit.objects.get();self.assertNotIn('expectedScore',audit.details_json);self.assertEqual(audit.action,'COMPARE')

    def test_compare_difference_does_not_claim_pass(self):
        response=views_archive.compare_evidence(self.req('post',{'sampleRef':'manual','expectedScore':'80','expectedGrade':'QUALIFIED'}),self.ctx.result.id,1)
        self.assertEqual(json.loads(response.content)['data']['status'],'DIFFERENT')

    def test_compare_bad_numeric_and_missing_ref_rejected(self):
        for score in ('NaN','Infinity','1.234',True,None):
            with self.subTest(score=score):
                r=views_archive.compare_evidence(self.req('post',{'sampleRef':'a','expectedScore':score,'expectedGrade':'QUALIFIED'}),self.ctx.result.id,1)
                self.assertEqual(r.status_code,400)
        r=views_archive.compare_evidence(self.req('post',{'expectedScore':'88','expectedGrade':'QUALIFIED'}),self.ctx.result.id,1);self.assertEqual(r.status_code,400)

    def test_access_audit_append_only(self):
        self.read();a=HrAssessmentArchiveAccessAudit.objects.get()
        for action in (lambda:a.save(),lambda:a.delete(),lambda:HrAssessmentArchiveAccessAudit.objects.all().update(purpose='change'),lambda:HrAssessmentArchiveAccessAudit.objects.all().delete(),lambda:HrAssessmentArchiveAccessAudit.objects.bulk_create([a])):
            with self.assertRaises(ValueError):action()

    def test_lifecycle_lists_original_name_and_archive_version(self):
        from hr_assessment.api.views_assessment import result_lifecycle_list
        HrSubjectSnapshot.objects.filter(pk=self.ctx.subject.pk).update(display_name='Current Name')
        r=result_lifecycle_list(self.req());self.assertEqual(r.status_code,200)
        row=json.loads(r.content)['data'][0]
        self.assertEqual(row['staffName'],self.ctx.subject.display_name)
        self.assertTrue(row['actions']['canReadArchive']);self.assertFalse(row['actions']['canExportArchive'])
        self.assertEqual(row['archiveVersions'][0]['version'],1)


class VerifiedFileTests(TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.settings_override=override_settings(MEDIA_ROOT=self.tmp.name);self.settings_override.enable();self.addCleanup(self.settings_override.disable)
        self.payload=b'%PDF-1.4\nverified test content\n'
        self.path=Path(self.tmp.name)/'protected/hr12/77/decision-minutes/test.pdf';self.path.parent.mkdir(parents=True);self.path.write_bytes(self.payload)
        self.doc=HrAssessmentDocument.objects.create(tenant_id=77,document_type='MINUTES',related_object_type='DECISION_SESSION',related_object_id=uuid.uuid4(),storage_key='protected/hr12/77/decision-minutes/test.pdf',original_filename='审定纪要.pdf',content_type='application/pdf',size_bytes=len(self.payload),sha256=hashlib.sha256(self.payload).hexdigest(),sealed_at=timezone.now())

    def test_verify_and_stream_same_bytes_without_reopening(self):
        stream=open_verified_document(self.doc);self.path.write_bytes(b'changed after verified')
        with stream:self.assertEqual(stream.read(),self.payload)

    def test_same_length_changed_bytes_rejected(self):
        self.path.write_bytes(b'x'*len(self.payload))
        with self.assertRaises(AssessmentDocumentError):open_verified_document(self.doc)

    def test_truncated_and_oversize_bytes_rejected(self):
        for payload in (b'a',b'a'*(len(self.payload)+1)):
            self.path.write_bytes(payload)
            with self.assertRaises(AssessmentDocumentError):open_verified_document(self.doc)

    def test_missing_file_rejected(self):
        self.path.unlink()
        with self.assertRaises(AssessmentDocumentError):open_verified_document(self.doc)

    def test_symbolic_file_and_directory_rejected(self):
        original=self.path.with_name('elsewhere');original.write_bytes(self.payload);self.path.unlink();self.path.symlink_to(original)
        with self.assertRaises(AssessmentDocumentError):open_verified_document(self.doc)
        self.path.unlink();parent=self.path.parent;parent.rename(parent.with_name('real'));parent.symlink_to(parent.with_name('real'),target_is_directory=True)
        with self.assertRaises(AssessmentDocumentError):open_verified_document(self.doc)

    def test_wrong_school_path_and_parent_path_rejected(self):
        for key in ('protected/hr12/88/decision-minutes/test.pdf','../test.pdf','/tmp/test.pdf','protected/hr12/77/../test.pdf'):
            self.doc.storage_key=key
            with self.assertRaises(AssessmentDocumentError):open_verified_document(self.doc)

    def test_invalid_hash_and_zero_size_rejected(self):
        self.doc.sha256='g'*64
        with self.assertRaises(AssessmentDocumentError):open_verified_document(self.doc)
        self.doc.sha256=hashlib.sha256(self.payload).hexdigest();self.doc.size_bytes=0
        with self.assertRaises(AssessmentDocumentError):open_verified_document(self.doc)

    def test_new_archive_checks_decision_document_bytes(self):
        c=make_case();
        # Fixture constructs a new formal result linked to the existing sealed document.
        c2=make_case();c2.result.decision_session_id=self.doc.related_object_id
        from hr_assessment.services.archive_evidence import capture_evidence
        # Persisted result is immutable: test a properly constructed separate result.
        result=HrFinalAssessmentResult.objects.create(tenant_id=77,case_id=uuid.uuid4(),assessment_type='ANNUAL',cycle_id=c2.result.cycle_id,grade_code='QUALIFIED',calculated_score=Decimal('88.50'),calculation_snapshot_json=c2.result.calculation_snapshot_json,decision_session_id=self.doc.related_object_id)
        self.path.write_bytes(b'bad')
        with self.assertRaises(AssessmentDocumentError):capture_evidence(result,1)


class MySQLArchiveSealTests(TestCase):
    def test_raw_archive_and_audit_updates_rejected_by_mysql(self):
        if connection.vendor!='mysql':self.skipTest('Requires migrated MySQL 8.4; SQLite is not proof of triggers.')
        a=archive_case(make_case())
        audit=HrAssessmentArchiveAccessAudit.objects.create(tenant_id=77,archive=a,actor_user_id=1,action='VIEW',purpose='database seal acceptance',content_hash=a.content_hash)
        for table,pk,col,value in [('hr_assessment_archive_package',a.id,'archive_status','PENDING'),('hr12_archive_access_audit',audit.id,'purpose','changed')]:
            with self.assertRaises(DatabaseError),transaction.atomic():
                with connection.cursor() as cursor:cursor.execute(f'UPDATE {table} SET {col}=%s WHERE id=%s',[value,pk.hex])


class SourceOwnedHR09Tests(TestCase):
    def setUp(self):
        from hr_staff.models import HrPerson, HrStaffMaster
        from hr_qualification.models import HrCredentialCatalogItem, HrPersonCredential, HrCredentialDocument
        from hr_qualification.constants import CredentialCategory, CredentialStatus, VerificationResult
        self.person=HrPerson.objects.create(tenant_id=77,legal_name='真实ORM样本教师')
        self.staff=HrStaffMaster.objects.create(tenant_id=77,person_id=self.person,staff_no='FUSION-HR09')
        catalog=HrCredentialCatalogItem.objects.create(tenant_id=77,code='TEST-CERT',category=CredentialCategory.VOCATIONAL_QUALIFICATION,name='资格样本')
        self.credential=HrPersonCredential.objects.create(tenant_id=77,person_id=self.person,staff_master_id=self.staff,catalog_item_id=catalog,credential_name_snapshot=catalog.name,issuer_name='合成机构',valid_from=timezone.localdate(),status=CredentialStatus.ACTIVE,current_verification_status=VerificationResult.VERIFIED,last_verified_at=timezone.now())
        self.doc=HrCredentialDocument.objects.create(credential_id=self.credential,file_id='storage-reference',version_no=3,checksum='b'*64,verified=True)

    def evidence(self):
        from hr_qualification.public import get_formal_credential_evidence
        return get_formal_credential_evidence(tenant_id=77,staff_ids=[self.staff.id],as_of=timezone.localdate()).rows[0]

    def test_public_snapshot_captures_actual_document_version_and_digest(self):
        row=self.evidence();doc=row.snapshot()['document_snapshots'][0]
        self.assertEqual(doc['documentId'],str(self.doc.id));self.assertEqual(doc['version'],3)
        self.assertEqual(doc['sha256'],'b'*64);self.assertFalse(doc['bytesVerified'])

    def test_new_document_and_changed_live_metadata_do_not_rewrite_archive(self):
        from hr_qualification.models import HrCredentialDocument
        payload=self.evidence().snapshot()
        a=archive_case(make_case(staff_id=self.staff.id,credential_payload=payload))
        HrCredentialDocument.objects.filter(pk=self.doc.pk).update(checksum='c'*64,version_no=9)
        HrCredentialDocument.objects.create(credential_id=self.credential,file_id='new-file',version_no=10,checksum='d'*64,verified=True)
        proof=archive_projection(a)
        self.assertEqual(len(proof['attachments']),1);self.assertEqual(proof['attachments'][0]['version'],3)
        self.assertEqual(proof['attachments'][0]['sha256'],'b'*64)

    def test_unverified_document_not_in_formal_snapshot(self):
        from hr_qualification.models import HrCredentialDocument
        HrCredentialDocument.objects.create(credential_id=self.credential,file_id='not-verified',version_no=4,verified=False)
        self.assertEqual(len(self.evidence().snapshot()['document_snapshots']),1)

    def test_current_metadata_lookup_does_not_write_new_records(self):
        from hr_qualification.models import HrCredentialDocument
        n=HrCredentialDocument.objects.count();self.evidence();self.evidence();self.assertEqual(HrCredentialDocument.objects.count(),n)

    def test_snapshot_lists_are_detached(self):
        row=self.evidence();p=row.snapshot();p['document_snapshots'][0]['version']=100
        self.assertEqual(row.snapshot()['document_snapshots'][0]['version'],3)

    def test_blank_checksum_remains_explicitly_unverified(self):
        from hr_qualification.models import HrCredentialDocument
        HrCredentialDocument.objects.filter(pk=self.doc.pk).update(checksum='')
        a=archive_case(make_case(staff_id=self.staff.id,credential_payload=self.evidence().snapshot()))
        self.assertEqual(archive_projection(a)['attachments'][0]['verificationStatus'],'CHECKSUM_NOT_CAPTURED')


class ArchiveBoundaryExtraTests(TestCase):
    def test_missing_score_never_reports_match(self):
        a=archive_case(make_case(score=None));request=RequestFactory().post('/',data=json.dumps({'expectedScore':'0','expectedGrade':'QUALIFIED','sampleRef':'zero'}),content_type='application/json')
        request.tenant_id=77;request.user=get_user_model().objects.create_superuser(username='zero',password='test-pass',email='none@example.invalid')
        request.META['HTTP_X_HR_ACCESS_REASON']='验收缺分数'
        response=views_archive.compare_evidence(request,a.result_id,1)
        self.assertEqual(json.loads(response.content)['data']['status'],'NOT_EVALUATED')

    def test_compare_csrf_missing_token_rejected_by_actual_middleware(self):
        from django.middleware.csrf import CsrfViewMiddleware
        request=RequestFactory().post('/',data='{}',content_type='application/json')
        response=CsrfViewMiddleware(lambda req:None).process_view(request,views_archive.compare_evidence,[],{})
        self.assertEqual(response.status_code,403)

    def test_corrupt_archive_not_returned_as_valid_provider_data(self):
        from hr_assessment.providers.interfaces import ArchiveProvider
        from hr_assessment.providers.base import ProviderContext, ProviderStatus
        c=make_case();a=archive_case(c)
        models.QuerySet.update(HrAssessmentArchivePackage.objects.filter(pk=a.pk),content_hash='f'*64)
        result=ArchiveProvider().fetch(ProviderContext(tenant_id=77,ids=[c.staff],as_of=timezone.now()))
        self.assertEqual(result.status,ProviderStatus.UNAVAILABLE);self.assertEqual(result.data,[])

    def test_valid_archive_is_returned_by_original_provider(self):
        from hr_assessment.providers.interfaces import ArchiveProvider
        from hr_assessment.providers.base import ProviderContext, ProviderStatus
        c=make_case();a=archive_case(c)
        result=ArchiveProvider().fetch(ProviderContext(tenant_id=77,ids=[c.staff],as_of=timezone.now()))
        self.assertEqual(result.status,ProviderStatus.OK);self.assertEqual(result.data[0]['contentHash'],a.content_hash)

    def test_complete_binding_cannot_reference_unready_sources(self):
        c=make_case()
        models.QuerySet.update(HrProviderSnapshotSet.objects.filter(pk=c.snapshot.pk),status='BLOCKED')
        with self.assertRaises(ArchiveEvidenceError):freeze_result_context(c.case)

    def test_raw_delete_audit_requires_mysql(self):
        if connection.vendor!='mysql':self.skipTest('Requires migrated MySQL 8.4, not SQLite.')
        a=archive_case(make_case())
        with self.assertRaises(DatabaseError),transaction.atomic():
            with connection.cursor() as cursor:cursor.execute('DELETE FROM hr_assessment_archive_package WHERE id=%s',[a.id.hex])


def finalized_workflow_from_hr09(staff, credential_payload):
    """Real HR12 policy/capture/finalization/lifecycle, HR03 person envelope fixture.

    Used for the integration test and browser evidence only, never initialization.
    """
    from hr_assessment.models import (HrAssessmentPolicyPack, HrAssessmentPolicyVersion,
        HrIndicatorSetVersion, HrIndicatorDefinition, HrIndicatorVersion,
        HrResultRuleVersion, HrReviewerAssignment, HrReviewerEvaluation, HrAssessmentDecisionSession)
    from hr_assessment.models.policy import HrIndicatorBinding
    from hr_assessment.service.evidence import ProviderEvidenceSnapshotService
    from hr_assessment.services.finalization_service import AssessmentFinalizationService, FinalResultInput
    from hr_assessment.providers.base import ProviderResult, ProviderStatus
    now=timezone.now();token=uuid.uuid4().hex
    rule=HrResultRuleVersion.objects.create(tenant_id=77,name='学校批准的年度等级样例',version_no=1,status='PUBLISHED',score_to_grade_mapping={'bands':[{'gradeCode':'QUALIFIED','minScore':'0','maxScore':'100','displayGrade':{'zh-CN':'合格'}}]})
    indicators=HrIndicatorSetVersion.objects.create(tenant_id=77,name='资格与评议依据',version_no=1,status='PUBLISHED',total_weight=Decimal('1.00'))
    definition=HrIndicatorDefinition.objects.create(tenant_id=77,code='QUAL-'+token,name='资格依据',dimension='PERFORMANCE')
    indicator=HrIndicatorVersion.objects.create(tenant_id=77,indicator=definition,version_no=1,status='PUBLISHED',name='資格依据',dimension='PERFORMANCE',value_type='NUMBER',source_provider='HR09',valid_from=now.date())
    HrIndicatorBinding.objects.create(id=uuid.uuid4(),indicator_set=indicators,indicator_version=indicator,weight=Decimal('1.0000'),required=True)
    pack=HrAssessmentPolicyPack.objects.create(tenant_id=77,code='F-'+token,name='学院年度考核样例',assessment_domain='ANNUAL')
    policy=HrAssessmentPolicyVersion.objects.create(tenant_id=77,policy_pack=pack,version_no=1,status='PUBLISHED',effective_from=now.date(),assessment_types=['ANNUAL'],rating_scale_version_id=uuid.uuid4(),indicator_set_version_id=indicators.id,workflow_version_id=uuid.uuid4(),result_rule_version_id=rule.id)
    cycle=HrAssessmentCycle.objects.create(tenant_id=77,cycle_no='C-'+token,name='2026年度考核 · 合成验收样例',assessment_type='ANNUAL',start_at=now.replace(month=1,day=1),end_at=now,policy_version_id=policy.id,lifecycle_status='REVIEWING')
    HrCycleSnapshot.objects.create(tenant_id=77,cycle=cycle,frozen_policy_json={'id':str(policy.id),'contentHash':policy.content_hash,'resultRule':{'id':str(rule.id),'contentHash':rule.content_hash,'scoreToGradeMapping':rule.score_to_grade_mapping}},frozen_reviewer_rules_json={'scoreAggregation':'AVERAGE','scoreField':'totalScore'},frozen_rating_scale_json={'minValue':'0','maxValue':'100'})
    case=HrAssessmentCase.objects.create(tenant_id=77,cycle=cycle,staff_id=staff.id,assessment_type='ANNUAL',policy_version_id=policy.id,status='PROPOSED')
    subject=HrSubjectSnapshot.objects.create(tenant_id=77,case_id=case.id,staff_id=staff.id,display_name=staff.person_id.legal_name,staff_code=staff.staff_no,org_name='工程学院（合成）',position_name='专任教师',snapshot_at=now)
    case.subject_snapshot=subject;case.save()
    class Inputs:
        providers={'person':object(),'qualification':object()}
        def collect_one(self,tenant_id,staff_id,provider_name,**kwargs):
            data=[credential_payload] if provider_name=='qualification' else [{'staffId':str(staff.id),'displayName':staff.person_id.legal_name,'testSource':'HR03_ENVELOPE_FIXTURE'}]
            return ProviderResult(status=ProviderStatus.OK,data=data,source_version='hr09-credential-evidence-v1' if provider_name=='qualification' else 'explicit-test-person-envelope')
    ProviderEvidenceSnapshotService(77,orchestrator=Inputs()).capture_case_from_policy(case_id=case.id)
    case.refresh_from_db()
    for score in ('80','90'):
        assignment=HrReviewerAssignment.objects.create(tenant_id=77,case_id=case.id,reviewer_role='MEMBER',reviewer_staff_id=uuid.uuid4(),status='SUBMITTED')
        HrReviewerEvaluation.objects.create(tenant_id=77,assignment=assignment,rating_json={'totalScore':score},submitted_at=now,revision_no=1)
    decision=HrAssessmentDecisionSession.objects.create(tenant_id=77,cycle_id=cycle.id,case_refs_json=[str(case.id)],status='COMPLETED',meeting_at=now)
    result=AssessmentFinalizationService(77,actor_staff_id=uuid.uuid4()).finalize(case_id=case.id,payload=FinalResultInput(decision_reason='合成样本正式审定',decision_session_id=decision.id))
    service=AssessmentResultLifecycleService(77,actor_staff_id=staff.id)
    notice=service.issue_notice(result_id=result.id,notice_no='NOTICE-'+token,delivery_channel='PAPER')
    service.confirm_delivery(notice_id=notice.id,delivery_receipt_ref='合成签收回执-001')
    service.acknowledge(result_id=result.id,acknowledgement_status='RECEIVED_AGREE',employee_opinion='核对无误（合成）')
    archive=service.archive(result_id=result.id)
    return SimpleNamespace(case=case,cycle=cycle,subject=subject,result=result,archive=archive,staff=staff)


class FinalizationWiringTests(TestCase):
    def setUp(self):
        SourceOwnedHR09Tests.setUp(self)

    def test_original_formal_pipeline_computes_then_freezes_sources_and_archives(self):
        row=SourceOwnedHR09Tests.evidence(self)
        state=finalized_workflow_from_hr09(self.staff,row.snapshot())
        self.assertEqual(state.result.calculated_score,Decimal('85.00'))
        self.assertEqual(state.result.calculation_snapshot_json['evidenceBinding']['status'],'COMPLETE')
        self.assertEqual(archive_projection(state.archive)['attachments'][0]['version'],3)
        self.assertEqual(archive_projection(state.archive)['result']['calculatedScore'],'85.00')
        self.assertEqual(HrAssessmentArchivePackage.objects.filter(result=state.result).count(),1)
        # No score/grade formula was replaced by a nondegree training-points rule.
        self.assertEqual(state.result.calculation_snapshot_json['source'],'SUBMITTED_REVIEWER_EVALUATIONS')
