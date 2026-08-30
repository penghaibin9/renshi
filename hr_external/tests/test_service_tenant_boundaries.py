"""P0 regression tests for tenant-bound HR08 state mutation services.

These unit contracts intentionally do not need a database: they prove that a
caller-supplied model object is only a reference and every formal write first
re-resolves it through ``tenant_id + pk`` under ``select_for_update``.
"""

from types import SimpleNamespace
from inspect import signature
from unittest.mock import MagicMock, patch
from uuid import uuid4

from django.test import SimpleTestCase

from hr_external.models import (
    HrExternalAccessGrant,
    HrExternalContribution,
    HrExternalExitCase,
    HrExternalHiringCase,
    HrExternalImportJob,
    HrExternalMaterial,
    HrExternalRenewalReview,
    HrExternalServiceTask,
)
from hr_external.services.access_service import AccessScopeInvalid, AccessService
from hr_external.services.exit_service import ExitBlocked, ExitService
from hr_external.services.hiring_service import HiringCaseNotFound, HiringService
from hr_external.services.import_service import ImportService, ImportValidationError
from hr_external.services.industry_service import CrossTenantReference, IndustryService
from hr_external.services.material_service import MaterialAccessDenied, MaterialService
from hr_external.services.renewal_service import RenewalService, RenewalStateConflict
from hr_external.services.task_service import TaskOutsideEngagement, TaskService


class TenantBoundStateMutationTests(SimpleTestCase):
    tenant_id = 101

    @staticmethod
    def _foreign_reference():
        return SimpleNamespace(pk=uuid4(), tenant_id=202)

    def _assert_locked_tenant_lookup(self, model, invoke, exception):
        reference = self._foreign_reference()
        with patch.object(model, "objects") as objects:
            locked = objects.select_for_update.return_value
            locked.filter.return_value.first.return_value = None
            with self.assertRaises(exception):
                invoke(reference)
            objects.select_for_update.assert_called_once_with()
            locked.filter.assert_called_once_with(
                tenant_id=self.tenant_id, id=reference.pk
            )

    def test_exit_case_foreign_bare_instance_is_rejected_before_write(self):
        self._assert_locked_tenant_lookup(
            HrExternalExitCase,
            lambda case: ExitService.start_exit.__wrapped__(
                ExitService(), case, tenant_id=self.tenant_id
            ),
            ExitBlocked,
        )

    def test_task_foreign_bare_instance_is_rejected_before_write(self):
        self._assert_locked_tenant_lookup(
            HrExternalServiceTask,
            lambda task: TaskService.assign.__wrapped__(
                TaskService(), task, tenant_id=self.tenant_id
            ),
            TaskOutsideEngagement,
        )

    def test_contribution_foreign_bare_instance_is_rejected_before_write(self):
        self._assert_locked_tenant_lookup(
            HrExternalContribution,
            lambda contribution: IndustryService.verify_contribution.__wrapped__(
                IndustryService(),
                contribution,
                tenant_id=self.tenant_id,
                verified=True,
            ),
            CrossTenantReference,
        )

    def test_access_grant_foreign_bare_instance_is_rejected_before_write(self):
        self._assert_locked_tenant_lookup(
            HrExternalAccessGrant,
            lambda grant: AccessService.mark_revoked.__wrapped__(
                AccessService(), grant, tenant_id=self.tenant_id
            ),
            AccessScopeInvalid,
        )

    def test_material_foreign_bare_instance_is_rejected_before_ticket_issue(self):
        self._assert_locked_tenant_lookup(
            HrExternalMaterial,
            lambda material: MaterialService.issue_ticket.__wrapped__(
                MaterialService(), tenant_id=self.tenant_id, material=material
            ),
            MaterialAccessDenied,
        )

    def test_hiring_case_uses_locked_tenant_lookup(self):
        reference = self._foreign_reference()
        with patch.object(HrExternalHiringCase, "objects") as objects:
            locked = objects.select_for_update.return_value.select_related.return_value
            locked.filter.return_value.first.return_value = None
            with self.assertRaises(HiringCaseNotFound):
                HiringService.activate.__wrapped__(
                    HiringService(), reference, tenant_id=self.tenant_id
                )
            objects.select_for_update.assert_called_once_with()
            locked.filter.assert_called_once_with(
                tenant_id=self.tenant_id, id=reference.pk
            )

    def test_renewal_review_uses_locked_tenant_lookup(self):
        reference = self._foreign_reference()
        with patch.object(HrExternalRenewalReview, "objects") as objects:
            locked = objects.select_for_update.return_value.select_related.return_value
            locked.filter.return_value.first.return_value = None
            with self.assertRaises(RenewalStateConflict):
                RenewalService.decide.__wrapped__(
                    RenewalService(),
                    reference,
                    tenant_id=self.tenant_id,
                    decision="DO_NOT_RENEW",
                )
            objects.select_for_update.assert_called_once_with()
            locked.filter.assert_called_once_with(
                tenant_id=self.tenant_id, id=reference.pk
            )

    def test_import_job_uses_locked_tenant_lookup(self):
        reference = self._foreign_reference()
        with patch.object(HrExternalImportJob, "objects") as objects:
            locked = objects.select_for_update.return_value
            locked.filter.return_value.first.return_value = None
            with self.assertRaises(ImportValidationError):
                ImportService.confirm_job.__wrapped__(
                    ImportService(), reference, tenant_id=self.tenant_id
                )
            objects.select_for_update.assert_called_once_with()
            locked.filter.assert_called_once_with(
                tenant_id=self.tenant_id, id=reference.pk
            )

    def test_missing_tenant_cannot_use_legacy_bare_instance_signature(self):
        reference = MagicMock(pk=uuid4())
        with self.assertRaises(TypeError):
            signature(ExitService.start_exit.__wrapped__).bind(ExitService(), reference)
        with self.assertRaises(TypeError):
            signature(TaskService.assign.__wrapped__).bind(TaskService(), reference)
        with self.assertRaises(TypeError):
            signature(HiringService.activate.__wrapped__).bind(
                HiringService(), reference
            )
