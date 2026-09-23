"""P4 controlled single-person chain and P5 proof collector.

Uses original accepted-hire fixture, real ORM services and real permission rows.
Starts at an explicitly accepted Offer: not full zero-to-recruitment, production
login, MySQL concurrency, physical restore or an external account-opening proof.
School membership lookup is controlled only for assignment. Uploaded data is
synthetic; malware scanning is disabled only in these isolated test settings.
"""
import json
import tempfile
from datetime import timedelta
from unittest.mock import patch
from io import StringIO
from django.test import TestCase, override_settings
from django.utils import timezone
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command, CommandError
from hr_recruitment.tests import test_w_a_hire_to_staff_db_chain as baseline_fixture
TENANT=baseline_fixture.TENANT
from hr_onboarding.tests.test_school_templates_v10 import user, plan, MANAGE, PUBLISH
from hr_onboarding.services.school_template_service import SchoolTemplateService
from hr_onboarding.services.workflow_service import OnboardingWorkflowService, workflow_summary
from hr_onboarding.services.case_service import CaseService
from hr_onboarding.services.report_service import ReportService
from hr_onboarding.services.material_service import MaterialService
from hr_onboarding.services.activation_service import ActivationService
from hr_onboarding.services.delivery_snapshot import capture_models, compare_snapshots, MODEL_LABELS
from hr_onboarding.api.exceptions import Hr05ApiError, PermissionDeniedError, VersionConflictError
from hr_onboarding.constants import PersonMatchStatus, CaseStatus
from hr_onboarding.models import (HrOnboardingCase, HrOnboardingTaskInstance, HrOnboardingMaterial,
    HrOnboardingMaterialRequirement, HrOnboardingAuditEvent)
from hr_staff.models import HrPerson, HrStaffMaster, HrEmploymentRelationship, HrStaffAssignment
from hr_structure.models import HrPositionReservation

@override_settings(AUTHENTICATION_BACKENDS=['base.auth_backends.CompanyScopedBackend'], COMPANY_SCOPED_PERMISSIONS=False)
class DeliveryChainTests(TestCase):
    _handoff_to_hr05 = baseline_fixture.WAHireToStaffDatabaseChainTests._handoff_to_hr05

    def setUp(self):
        baseline_fixture.WAHireToStaffDatabaseChainTests.setUp(self)
        self.maker=user('delivery-maker',[MANAGE,'hr05.case.create','hr05.case.view','hr05.task.manage','hr05.case.activate'])
        self.checker=user('delivery-publisher',[PUBLISH])
        self.owner=user('delivery-owner',['hr05.task.complete'])
        self.other=user('delivery-other',['hr05.task.complete'])
        self.media=tempfile.TemporaryDirectory(); self.addCleanup(self.media.cleanup)
        setting=override_settings(MEDIA_ROOT=self.media.name, MALWARE_SCAN_REQUIRED=False)
        setting.enable(); self.addCleanup(setting.disable)
        membership=patch('base.auth_backends.get_allowed_company_ids',return_value={TENANT})
        membership.start(); self.addCleanup(membership.stop)
        self.wf=OnboardingWorkflowService(tenant_id=TENANT,user=self.maker)
        self.owned=OnboardingWorkflowService(tenant_id=TENANT,user=self.owner)
        self.service=SchoolTemplateService(tenant_id=TENANT,user=self.maker)

    def prepared(self):
        case=self._handoff_to_hr05()
        policy=plan(); policy['scope']={'staff_categories':[], 'employment_types':[]}
        policy['effective_from']=self.today.replace(month=1,day=1).isoformat()
        policy['tasks'][1]['blocking_level']='NON_BLOCKING'
        draft=self.service.save(plan=policy,idempotency_key='v12-plan')['version']
        published=SchoolTemplateService(tenant_id=TENANT,user=self.checker).publish(
            version_id=draft['id'],etag=draft['etag'],reason='受控校本清单核对',idempotency_key='v12-publish')['version']
        preview=self.service.preview(version_id=published['id'],case_id=case.id)
        self.assertTrue(preview['eligible'],preview)
        self.assertEqual(HrOnboardingTaskInstance.objects.count(),0)
        self.service.bind(version_id=published['id'],case_id=case.id,case_version=case.version,
            etag=published['etag'],idempotency_key='v12-bind')
        case.refresh_from_db()
        return case,published

    def report(self,case):
        case=CaseService(tenant_id=TENANT,actor_user_id=self.maker.id).mark_ready_to_report(case)
        ReportService(tenant_id=TENANT,actor_user_id=self.maker.id).confirm_report(case,
            actual_report_at=timezone.now()-timedelta(minutes=1),checked_identity=True)
        case.refresh_from_db();return case

    def verified(self,case):
        req=HrOnboardingMaterialRequirement.objects.get(template_version_id=case.template_version_id)
        svc=MaterialService(tenant_id=TENANT,actor_user_id=self.maker.id)
        m=svc.submit_material(case,req.id,SimpleUploadedFile('synthetic.pdf',b'%PDF-1.4\n synthetic original check\n%%EOF',content_type='application/pdf'))
        svc.verify_material(m,result='VERIFIED',reason='受控样本原件核验',evidence={'reference':'TEST-ONLY-ORIGINAL'})
        return m

    def activate(self,case):
        case=CaseService(tenant_id=TENANT,actor_user_id=self.maker.id).mark_ready_for_activation(case)
        case=CaseService(tenant_id=TENANT,actor_user_id=self.maker.id).resolve_person_match(case,
            person_id=None,status=PersonMatchStatus.EXACT_MATCH)
        result=ActivationService(tenant_id=TENANT,actor_user_id=self.maker.id).activate(
            case,effective_at=self.today,idempotency_key='v12-activate')
        self.assertTrue(result['activated'],result);case.refresh_from_db();return result

    def assigned(self,case,code='ACCOUNT'):
        task=HrOnboardingTaskInstance.objects.get(case=case,definition__code=code)
        self.wf.task_command(task_id=task.id,action='assign',version=task.version,
            idempotency_key='assign-'+code,data={'username':self.owner.username})
        task.refresh_from_db();return task

    def completed(self,task):
        self.owned.task_command(task_id=task.id,action='start',version=task.version,idempotency_key='start-'+str(task.id),data={})
        task.refresh_from_db()
        kwargs=dict(task_id=task.id,action='complete',version=task.version,idempotency_key='complete-'+str(task.id),
            data={'note':'受控人工办理完毕','evidence':'TEST-ONLY-NO-EXTERNAL-PROVISION'})
        out=self.owned.task_command(**kwargs)
        again=self.owned.task_command(**kwargs)
        self.assertEqual(out['receipt'],again['receipt']);self.assertTrue(again['replayed'])
        task.refresh_from_db();return task

    def test_one_person_config_handoff_report_material_owner_activation_closure(self):
        case,version=self.prepared();case=self.report(case);self.verified(case)
        task=self.assigned(case); self.completed(task)
        result=self.activate(case); case.refresh_from_db()
        summary=workflow_summary(case,self.maker)
        self.assertTrue(summary['can_complete'],summary['blockers'])
        args=dict(case_id=case.id,action='complete',version=case.version,idempotency_key='v12-close',fingerprint=summary['fingerprint'])
        first=self.wf.case_command(**args); again=self.wf.case_command(**args)
        self.assertEqual(first['receipt'],again['receipt']);self.assertTrue(again['replayed'])
        case.refresh_from_db();self.assertEqual(case.status,CaseStatus.ONBOARDING_COMPLETED)
        self.assertEqual(str(case.hr03_staff_master_id),result['staff_master_id'])
        for model in [HrPerson,HrStaffMaster,HrEmploymentRelationship,HrStaffAssignment]:
            self.assertEqual(model.objects.filter(tenant_id=TENANT).count(),1)
        self.assertNotEqual(HrOnboardingTaskInstance.objects.get(case=case,definition__code='CARD').status,'COMPLETED')
        self.reservation.refresh_from_db();self.assertEqual(self.reservation.status,HrPositionReservation.Status.COMMITTED)

    def test_missing_material_does_not_activate_or_create_staff(self):
        case,_=self.prepared();case=self.report(case)
        case=CaseService(tenant_id=TENANT).mark_ready_for_activation(case)
        gate=ActivationService(tenant_id=TENANT).gate(case,effective_at=self.today)
        self.assertFalse(gate.passed);self.assertEqual(HrStaffMaster.objects.filter(tenant_id=TENANT).count(),0)
        self.reservation.refresh_from_db();self.assertEqual(self.reservation.status,HrPositionReservation.Status.HELD)

    def test_non_owner_cannot_complete_another_persons_task(self):
        case,_=self.prepared();case=self.report(case);task=self.assigned(case)
        with self.assertRaises(PermissionDeniedError):
            OnboardingWorkflowService(tenant_id=TENANT,user=self.other).task_command(task_id=task.id,
                action='complete',version=task.version,idempotency_key='wrong-owner',data={'note':'x','evidence':'x'})
        task.refresh_from_db();self.assertNotEqual(task.status,'COMPLETED')

    def test_prerequisite_is_not_satisfied_by_assignment(self):
        case,_=self.prepared();case=self.report(case);task=self.assigned(case,'CARD')
        with self.assertRaises(Hr05ApiError):
            self.owned.task_command(task_id=task.id,action='start',version=task.version,idempotency_key='card-too-early',data={})
        task.refresh_from_db();self.assertNotEqual(task.status,'IN_PROGRESS')

    def test_old_owner_rejected_after_reassignment(self):
        case,_=self.prepared();case=self.report(case);task=self.assigned(case)
        self.wf.task_command(task_id=task.id,action='assign',version=task.version,idempotency_key='reassign',
            data={'username':self.other.username,'note':'原责任人交接工作'})
        with self.assertRaises(PermissionDeniedError):
            self.owned.task_command(task_id=task.id,action='start',version=task.version,idempotency_key='old-owner',data={})

    def test_wrong_school_cannot_close_case(self):
        case,_=self.prepared()
        with self.assertRaises(Hr05ApiError):
            OnboardingWorkflowService(tenant_id=TENANT+1,user=self.maker).case_command(case_id=case.id,
                action='complete',version=case.version,idempotency_key='other-school',fingerprint='x')

    def test_snapshot_collector_covers_real_models_and_detects_same_count_edit(self):
        case,_=self.prepared();key=b'only-controlled-test-key-32-bytes!!'
        first=capture_models(TENANT,key);same=capture_models(TENANT,key)
        self.assertEqual(set(first['models']),set(MODEL_LABELS));self.assertEqual(compare_snapshots(first,same)['status'],'MATCH')
        self.assertNotIn('W-A 张三',json.dumps(first,ensure_ascii=False))
        # Use an existing text column; this is a checksum mutation test, not a workflow action.
        HrOnboardingCase.objects.filter(pk=case.pk).update(employment_type='CONTROLLED_DIFFERENCE')
        changed=capture_models(TENANT,key)
        self.assertEqual(first['models']['hr_onboarding.HrOnboardingCase']['rows'],changed['models']['hr_onboarding.HrOnboardingCase']['rows'])
        self.assertEqual(compare_snapshots(first,changed)['status'],'MISMATCH')

    def test_real_mysql_snapshot_command_rejects_sqlite(self):
        with tempfile.TemporaryDirectory() as tmp:
            from pathlib import Path
            key=Path(tmp)/'key';key.write_bytes(b'k'*32);key.chmod(0o600)
            with self.assertRaises(CommandError):
                call_command('hr_delivery_snapshot',school_id=TENANT,key_file=str(key),output=str(Path(tmp)/'proof.json'),confirm_quiesced=True,stdout=StringIO())
            self.assertFalse((Path(tmp)/'proof.json').exists())
