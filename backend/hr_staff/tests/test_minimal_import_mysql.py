"""True transaction tests; requires MySQL and project migrations/dependencies."""
from datetime import timedelta
from unittest.mock import patch
from django.db import connection, transaction
from django.test import TestCase
from django.utils import timezone
from base.models import Company, Department
from hr_staff.api.imports import build_row_validator
from hr_staff.constants import ImportJobStatus
from hr_staff.models import (
    HrImportIssue, HrPerson, HrStaffMaster, HrEmploymentRelationship, HrStaffAssignment, HrStaffAuditEvent
)
from hr_staff.services.import_service import ImportService, ImportStateConflict, StaffMasterRowApplier

class MinimalImportMySQLTests(TestCase):
    def setUp(self):
        self.assertEqual(connection.vendor,'mysql','Real MySQL required, not SQLite or a fake ORM.')
        self.school=Company.objects.create(company='导入验收学校',hq=True)
        self.other=Company.objects.create(company='隔离校验学校',hq=False)
        self.department=Department.objects.entire().create(department='数学系')
        self.department.company_id.add(self.school)
        self.svc=ImportService(self.school.pk)

    def rows(self,**changes):
        row=dict(staff_no='REAL001',legal_name='验收教职工',department_name='数学系',
                 staff_category_code='教师',relationship_type='合同聘用',effective_from='2026-09-01',_source_row_no=4)
        row.update(changes);return [row]

    def preview(self,rows):
        validator=build_row_validator(self.school.pk,rows)
        with transaction.atomic():
            job=self.svc.create_job(template_key='staff_master')
            self.svc.parse_rows(job,rows);self.svc.validate_rows(job,validator)
        return job

    def test_preview_only_stages_and_preserves_actual_excel_row(self):
        job=self.preview(self.rows())
        self.assertEqual(job.valid_rows,1);self.assertEqual(job.rows.get().row_no,4)
        self.assertFalse(HrStaffMaster.objects.exists());self.assertFalse(HrPerson.objects.exists())

    def test_real_four_table_commit_readback_and_no_duplicate_replay(self):
        job=self.preview(self.rows());applier=StaffMasterRowApplier(self.school.pk)
        result=self.svc.commit(job,applier)
        self.assertEqual(result['committed'],1);self.assertTrue(result['readbackComplete'])
        for model in (HrPerson,HrStaffMaster,HrEmploymentRelationship,HrStaffAssignment):
            self.assertEqual(model.objects.filter(tenant_id=self.school.pk).count(),1)
            self.assertFalse(model.objects.filter(tenant_id=self.other.pk).exists())
        self.assertEqual(job.rows.get().result_ref,str(HrStaffMaster.objects.get().pk))
        self.assertEqual(self.svc.commit(job,applier),result)
        self.assertEqual(HrStaffMaster.objects.count(),1)

    def test_missing_department_and_true_employment_fields_fail_preview(self):
        job=self.preview(self.rows(department_name='',effective_from='',staff_category_code='',relationship_type=''))
        self.assertEqual(job.valid_rows,0);self.assertEqual(job.status,ImportJobStatus.VALIDATION_FAILED)
        self.assertFalse(HrStaffMaster.objects.exists())

    def test_cross_school_department_rejected(self):
        foreign=Department.objects.entire().create(department='他校部门');foreign.company_id.add(self.other)
        job=self.preview(self.rows(department_name='',legacy_department_id=str(foreign.pk)))
        self.assertEqual(job.valid_rows,0)

    def test_department_changed_after_preview_fails_no_person_left(self):
        job=self.preview(self.rows());self.department.company_id.remove(self.school)
        result=self.svc.commit(job,StaffMasterRowApplier(self.school.pk))
        self.assertEqual(result['failed'],1);self.assertEqual(result['committed'],0)
        self.assertFalse(HrPerson.objects.exists())

    def test_failure_in_fourth_table_rolls_back_first_three(self):
        job=self.preview(self.rows())
        with patch('hr_staff.services.assignment_service.AssignmentService.create_assignment',side_effect=RuntimeError('injected fourth table failure')):
            result=self.svc.commit(job,StaffMasterRowApplier(self.school.pk))
        self.assertEqual(result['committed'],0)
        for model in (HrPerson,HrStaffMaster,HrEmploymentRelationship,HrStaffAssignment):self.assertFalse(model.objects.exists())
        self.assertEqual(job.rows.get().commit_status,'FAILED')

    def test_active_claim_rejected_and_stale_claim_recovered(self):
        job=self.preview(self.rows());job.status=ImportJobStatus.COMMITTING
        job.checkpoint={'commit_token':'old-owner','commit_heartbeat_at':timezone.now().isoformat()};job.save()
        self.assertFalse(self.svc._result_for_job(job)['resumeAllowed'])
        with self.assertRaises(ImportStateConflict):self.svc.commit(job,StaffMasterRowApplier(self.school.pk))
        job.checkpoint['commit_heartbeat_at']=(timezone.now()-timedelta(hours=1)).isoformat();job.save()
        self.assertTrue(self.svc._result_for_job(job)['resumeAllowed'])
        self.assertEqual(self.svc.commit(job,StaffMasterRowApplier(self.school.pk))['committed'],1)
        with transaction.atomic():
            with self.assertRaises(ImportStateConflict):self.svc._owned_job(job.id,'old-owner')

    def test_other_school_cannot_find_job(self):
        job=self.preview(self.rows());self.assertIsNone(ImportService(self.other.pk).job_for_id(job.id))
    def test_historical_staging_cannot_reintroduce_removed_defaults(self):
        """Legacy staged data must be revalidated even if old preview said valid."""
        rows=[dict(staff_no='LEGACY001', legal_name='历史暂存教师',
                   legacy_department_id=str(self.department.pk), staff_category_code='',
                   relationship_type='', effective_from='', _source_row_no=11)]
        job=self.svc.create_job(template_key='staff_master')
        self.svc.parse_rows(job,rows)
        # Simulate a historical validator that incorrectly accepted the row.
        self.svc.validate_rows(job,row_validator=lambda row: {})
        self.assertEqual(job.status,ImportJobStatus.READY_TO_COMMIT)
        result=self.svc.commit(job,StaffMasterRowApplier(self.school.pk))
        self.assertEqual((result['committed'],result['failed']),(0,1))
        self.assertFalse(HrPerson.objects.exists())
        issues=set(HrImportIssue.objects.filter(job_id=job).values_list('field_code',flat=True))
        self.assertTrue({'staff_category_code','relationship_type','effective_from'} <= issues)

    def test_commit_revalidates_illegal_enum_and_real_calendar_date(self):
        rows=[dict(staff_no='LEGACY002', legal_name='非法历史行',
                   legacy_department_id=str(self.department.pk), staff_category_code='NOT_A_CATEGORY',
                   relationship_type='CONTRACT', effective_from='2026-02-30', _source_row_no=19)]
        job=self.svc.create_job(template_key='staff_master')
        self.svc.parse_rows(job,rows);self.svc.validate_rows(job,row_validator=lambda row: {})
        result=self.svc.commit(job,StaffMasterRowApplier(self.school.pk))
        self.assertEqual(result['committed'],0)
        self.assertFalse(HrStaffMaster.objects.exists())
        fields=set(HrImportIssue.objects.filter(job_id=job,error_code='COMMIT_VALIDATION_ERROR')
                   .values_list('field_code',flat=True))
        self.assertTrue({'staff_category_code','effective_from'} <= fields)

    def test_authority_readback_covers_person_staff_employment_assignment(self):
        job=self.preview(self.rows(staff_no='READBACK001'))
        result=self.svc.commit(job,StaffMasterRowApplier(self.school.pk,actor_user_id=77))
        self.assertTrue(result['readbackComplete'])
        self.assertEqual(result['readbackScope'],'PERSON_STAFF_EMPLOYMENT_ASSIGNMENT')
        self.assertEqual(result['readbackCount'],1)
        self.assertTrue(HrStaffAuditEvent.objects.filter(
            tenant_id=self.school.pk,action='IMPORT_ROW_COMMITTED',business_id=f'{job.id}:4'
        ).exists())

    def test_first_use_readiness_requires_complete_four_layer_authority(self):
        from base.first_use import _has_complete_hr03_staff_authority

        job=self.preview(self.rows(staff_no='READY001'))
        self.svc.commit(job,StaffMasterRowApplier(self.school.pk))
        self.assertTrue(_has_complete_hr03_staff_authority(self.school.pk))

        assignment=HrStaffAssignment.objects.get(tenant_id=self.school.pk)
        assignment.delete()
        self.assertFalse(_has_complete_hr03_staff_authority(self.school.pk))

    def test_half_staff_master_never_marks_first_use_staff_ready(self):
        from base.first_use import _has_complete_hr03_staff_authority
        from hr_staff.models import HrPerson

        person=HrPerson.objects.create(tenant_id=self.school.pk,legal_name='半条人员')
        HrStaffMaster.objects.create(
            tenant_id=self.school.pk, person_id=person, staff_no='HALF001',
            staff_category_code='TEACHER'
        )
        self.assertFalse(_has_complete_hr03_staff_authority(self.school.pk))

    def test_missing_authority_layer_is_not_reported_as_verified_success(self):
        job=self.preview(self.rows(staff_no='READBACK002'))
        self.svc.commit(job,StaffMasterRowApplier(self.school.pk))
        HrStaffAssignment.objects.filter(tenant_id=self.school.pk).delete()
        result=self.svc._result_for_job(job)
        self.assertEqual(result['committed'],1)
        self.assertEqual(result['readbackCount'],0)
        self.assertFalse(result['readbackComplete'])

    def test_import_row_audit_failure_rolls_back_all_authority_tables(self):
        from hr_staff.services.audit_service import write_audit_event as real_write
        def fail_only_import_receipt(**kwargs):
            if kwargs.get('action') == 'IMPORT_ROW_COMMITTED':
                raise RuntimeError('injected import receipt audit failure')
            return real_write(**kwargs)
        job=self.preview(self.rows(staff_no='AUDITROLLBACK001'))
        with patch('hr_staff.services.audit_service.write_audit_event',side_effect=fail_only_import_receipt):
            result=self.svc.commit(job,StaffMasterRowApplier(self.school.pk,actor_user_id=77))
        self.assertEqual(result['committed'],0)
        for model in (HrPerson,HrStaffMaster,HrEmploymentRelationship,HrStaffAssignment):
            self.assertFalse(model.objects.filter(tenant_id=self.school.pk).exists())
        self.assertEqual(job.rows.get().commit_status,'FAILED')

    def test_repeat_after_stale_recovery_never_increases_authority_counts(self):
        job=self.preview(self.rows(staff_no='RECOVER001'))
        job.status=ImportJobStatus.COMMITTING
        old=timezone.now()-timedelta(hours=1)
        job.checkpoint={'commit_token':'dead-owner','commit_started_at':old.isoformat(),
                        'commit_heartbeat_at':old.isoformat()}
        job.save(update_fields=['status','checkpoint'])
        first=self.svc.commit(job,StaffMasterRowApplier(self.school.pk))
        counts=[m.objects.filter(tenant_id=self.school.pk).count()
                for m in (HrPerson,HrStaffMaster,HrEmploymentRelationship,HrStaffAssignment)]
        second=self.svc.commit(job,StaffMasterRowApplier(self.school.pk))
        self.assertEqual(first,second)
        self.assertEqual(counts,[1,1,1,1])
        self.assertEqual(counts,[m.objects.filter(tenant_id=self.school.pk).count()
                                 for m in (HrPerson,HrStaffMaster,HrEmploymentRelationship,HrStaffAssignment)])
        with transaction.atomic():
            with self.assertRaises(ImportStateConflict):
                self.svc._owned_job(job.id,'dead-owner')


    def _map_department_to_hr02(self):
        from hr_structure.models import HrLegacyObjectLink, HrOrganization, HrOrganizationVersion
        org=HrOrganization.objects.create(
            tenant_id=self.school.pk,stable_code='ORG-MATH',org_dimension='ADMIN',identity_status='ACTIVE'
        )
        HrOrganizationVersion.objects.create(
            organization_id=org,tenant_id=self.school.pk,name='数学系',org_type='DEPARTMENT',
            validity_from=timezone.localdate()-timedelta(days=3650),version_no=1,status='EFFECTIVE'
        )
        HrLegacyObjectLink.objects.create(
            tenant_id=self.school.pk,domain_entity_type='organization',domain_entity_id=str(org.pk),
            legacy_app='base',legacy_model='department',legacy_pk=str(self.department.pk),link_status='MAPPED'
        )
        return org

    def test_mapped_department_import_writes_legacy_and_hr02_authority_refs(self):
        org=self._map_department_to_hr02()
        job=self.preview(self.rows(staff_no='MAP001'))
        result=self.svc.commit(job,StaffMasterRowApplier(self.school.pk))
        self.assertEqual((result['committed'],result['failed']),(1,0))
        assignment=HrStaffAssignment.objects.get(tenant_id=self.school.pk)
        self.assertEqual(assignment.legacy_department_id,self.department.pk)
        self.assertEqual(assignment.organization_id_id,org.pk)

    def test_hr02_authority_mode_rejects_unmapped_department_at_preview(self):
        from hr_structure.models import Hr02AuthorityCutover
        Hr02AuthorityCutover.objects.create(
            tenant_id=self.school.pk,mode=Hr02AuthorityCutover.Mode.HR02_AUTHORITY,
            operator='test',reason='mysql acceptance',reconcile_report_id='R-TEST'
        )
        job=self.preview(self.rows(staff_no='AUTH-NOMAP'))
        self.assertEqual(job.valid_rows,0)
        self.assertEqual(job.status,ImportJobStatus.VALIDATION_FAILED)
        self.assertFalse(HrStaffMaster.objects.exists())

    def test_hr02_authority_mode_accepts_mapped_department_and_first_use(self):
        from base.first_use import _has_complete_hr03_staff_authority
        from hr_structure.models import Hr02AuthorityCutover
        org=self._map_department_to_hr02()
        Hr02AuthorityCutover.objects.create(
            tenant_id=self.school.pk,mode=Hr02AuthorityCutover.Mode.HR02_AUTHORITY,
            operator='test',reason='mysql acceptance',reconcile_report_id='R-TEST'
        )
        job=self.preview(self.rows(staff_no='AUTH-MAP'))
        result=self.svc.commit(job,StaffMasterRowApplier(self.school.pk))
        self.assertEqual(result['committed'],1)
        assignment=HrStaffAssignment.objects.get(tenant_id=self.school.pk)
        self.assertEqual(assignment.organization_id_id,org.pk)
        self.assertTrue(_has_complete_hr03_staff_authority(self.school.pk))

    def test_first_use_requires_current_effective_assignment_not_historical_row(self):
        from base.first_use import _has_complete_hr03_staff_authority
        job=self.preview(self.rows(staff_no='HISTORY001'))
        self.svc.commit(job,StaffMasterRowApplier(self.school.pk))
        assignment=HrStaffAssignment.objects.get(tenant_id=self.school.pk)
        assignment.effective_to=timezone.localdate()-timedelta(days=1)
        assignment.status='ENDED'
        assignment.save(update_fields=['effective_to','status','updated_at'])
        self.assertFalse(_has_complete_hr03_staff_authority(self.school.pk))
