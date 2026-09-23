"""Trusted actor bound to an existing real proposal. No payload impersonation."""
from django.test import TestCase
from hr_recruitment.tests import test_offer_s8 as seed
from hr_recruitment.models import HrProposedHire
from hr_recruitment.services.proposed_hire_service import ProposedHireService, ProposedHireServiceError

class ApproverIdentityV8Tests(TestCase):
    def setUp(self):
        seed.OfferFlowTests.setUp(self)
        # Explicitly restore a pending fixture; production code cannot bypass approval.
        HrProposedHire.objects.filter(pk=self.proposed.pk).update(approval_status='PROPOSE',approved_by='',approved_at=None)
    def test_spoofed_actor_is_rejected_without_mutation(self):
        with self.assertRaises(ProposedHireServiceError) as c:
            ProposedHireService(tenant_id=seed.TENANT,actor='AUTHENTICATED-42').decide(proposed_hire_id=self.proposed.id,decision='APPROVE',approving_user='ATTACKER-99')
        self.assertEqual(c.exception.code,'APPROVER_IDENTITY_MISMATCH')
        self.proposed.refresh_from_db();self.assertEqual(self.proposed.approval_status,'PROPOSE')
    def test_current_actor_is_recorded(self):
        result=ProposedHireService(tenant_id=seed.TENANT,actor='AUTHENTICATED-42').decide(proposed_hire_id=self.proposed.id,decision='APPROVE',reason='核实录用依据')
        self.assertEqual(result.approved_by,'AUTHENTICATED-42')
    def test_missing_actor_cannot_approve(self):
        with self.assertRaises(ProposedHireServiceError) as c:
            ProposedHireService(tenant_id=seed.TENANT,actor='').decide(proposed_hire_id=self.proposed.id,decision='APPROVE')
        self.assertEqual(c.exception.code,'APPROVER_CONTEXT_REQUIRED')
