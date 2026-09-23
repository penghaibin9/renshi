"""HR04 real ORM read/transition guards; controlled role context, no production SSO."""
from datetime import date
from types import SimpleNamespace
import json
from unittest.mock import patch
from uuid import uuid4
from django.test import TestCase, RequestFactory
from django.db import connection
from django.test.utils import CaptureQueriesContext
from hr_recruitment.tests import test_offer_s8 as seed
from hr_recruitment.api.proposed_hire import proposed_hire_list, transition_offer
from hr_recruitment.models import HrRecruitmentOffer, HrProposedHire, HrSelectionResultSnapshot, HrRecruitmentAuditEvent
from hr_recruitment.services.offer_service import OfferService, OfferServiceError, offer_snapshot


class OperationalReadV9Tests(TestCase):
    def setUp(self):
        seed.OfferFlowTests.setUp(self)
        self.offer_service=OfferService(tenant_id=seed.TENANT, actor='signed-in-user')
        self.offer=self.offer_service.create_offer(proposed_hire_id=self.proposed.id,offer_no='OFFER-SAVED',employment_type='FULL_TIME',expected_report_date='2026-10-01')
        self.user=SimpleNamespace(id=88,is_superuser=True,is_authenticated=True,is_active=True)

    def read(self,**params):
        request=RequestFactory().get('/api/v1/hr/recruitment/proposed-hires',params);request.user=self.user
        with patch('hr_recruitment.api.proposed_hire.make_hr04_context',return_value=SimpleNamespace(tenant_id=seed.TENANT)):
            res=proposed_hire_list(request)
        return res,json.loads(res.content)

    def test_offer_saved_terms_are_returned_not_only_id_and_state(self):
        res,data=self.read();self.assertEqual(res.status_code,200)
        o=data['data']['items'][0]['offer_snapshot']
        self.assertEqual(o['expected_report_date'],'2026-10-01');self.assertEqual(o['employment_type'],'FULL_TIME')
        self.assertEqual(o['fingerprint'],offer_snapshot(self.offer)['fingerprint'])
        self.assertNotIn('primary_email',json.dumps(o))

    def test_lookup_name_and_stable_page_past_100(self):
        # Seed additional proposals without business advancement; exercises DB pagination.
        HrProposedHire.objects.bulk_create([HrProposedHire(tenant_id=seed.TENANT,application_id=self.app,
            recruitment_position_id=self.position,rank=i+2,final_score=90) for i in range(104)])
        res,data=self.read(page=6,pageSize=20)
        self.assertEqual(data['data']['total'],105);self.assertEqual(len(data['data']['items']),5)
        self.assertFalse(data['data']['hasNext'])
        self.assertEqual(self.read(keyword='不存在')[1]['data']['total'],0)
        self.assertEqual(self.read(keyword=self.candidate.legal_name)[1]['data']['total'],105)

    def test_existing_proposal_on_other_page_is_never_eligible_again(self):
        HrProposedHire.objects.bulk_create([HrProposedHire(tenant_id=seed.TENANT,application_id=self.app,
            recruitment_position_id=self.position,rank=i+2,final_score=90) for i in range(2)])
        self.app.canonical_status='QUALIFIED';self.app.save()
        HrSelectionResultSnapshot.objects.get_or_create(tenant_id=seed.TENANT,application_id=self.app,
            recruitment_position_id=self.position,snapshot_version=100,rank=1,defaults={'final_score':90})
        self.assertEqual(self.read(page=2,pageSize=1)[1]['data']['eligible_applications'],[])

    def test_offer_read_respects_specific_permission(self):
        self.user.is_superuser=False;self.user.has_perm=lambda p:p=='hr04.proposed_hire.manage'
        self.assertIsNone(self.read()[1]['data']['items'][0]['offer_snapshot'])

    def test_cross_tenant_proposal_not_visible_or_creatable(self):
        self.proposed.tenant_id=999;self.proposed.save()
        self.assertEqual(self.read()[1]['data']['total'],0)
        with self.assertRaises(OfferServiceError):self.offer_service.create_offer(proposed_hire_id=self.proposed.id,offer_no='ILLEGAL')
        with self.assertRaises(OfferServiceError):self.offer_service.transition(offer_id=self.offer.id,target='APPROVED')

    def test_approval_binds_exact_terms_even_if_version_not_incremented(self):
        fingerprint=offer_snapshot(self.offer)['fingerprint']
        HrRecruitmentOffer.objects.filter(pk=self.offer.id).update(expected_report_date=date(2026,10,9))
        with self.assertRaises(OfferServiceError) as cm:
            self.offer_service.transition(offer_id=self.offer.id,target='APPROVED',expected_fingerprint=fingerprint)
        self.assertEqual(cm.exception.code,'OFFER_VERSION_CONFLICT');self.offer.refresh_from_db();self.assertEqual(self.offer.status,'DRAFT')

    def test_valid_version_records_actual_actor_and_content_hash(self):
        fingerprint=offer_snapshot(self.offer)['fingerprint']
        o=self.offer_service.transition(offer_id=self.offer.id,target='APPROVED',expected_fingerprint=fingerprint)
        audit=HrRecruitmentAuditEvent.objects.get(event_type='OFFER_STATUS_CHANGED')
        self.assertEqual(audit.actor_id,'signed-in-user');self.assertEqual(audit.before_json['fingerprint'],fingerprint)
        self.assertEqual(audit.after_json['version'],o.version)

    def test_approval_and_audit_are_atomic(self):
        with patch('hr_recruitment.services.offer_service.audit_event',side_effect=RuntimeError('audit storage unavailable')):
            with self.assertRaises(RuntimeError):self.offer_service.transition(offer_id=self.offer.id,target='APPROVED')
        self.offer.refresh_from_db();self.assertEqual(self.offer.status,'DRAFT')

    def test_http_transition_requires_fingerprint(self):
        request=RequestFactory().post('/',json.dumps({'target':'APPROVED'}),content_type='application/json');request.user=self.user
        with patch('hr_recruitment.api.proposed_hire.make_hr04_context',return_value=SimpleNamespace(tenant_id=seed.TENANT)):
            res=transition_offer(request,self.offer.id)
        self.assertEqual(res.status_code,422);self.offer.refresh_from_db();self.assertEqual(self.offer.status,'DRAFT')

    def test_invalid_pagination_does_not_raise_500(self):
        self.assertEqual(self.read(page='bad')[0].status_code,422)

    def test_page_children_do_not_produce_n_plus_one_queries(self):
        HrProposedHire.objects.bulk_create([HrProposedHire(tenant_id=seed.TENANT,application_id=self.app,
            recruitment_position_id=self.position,rank=i+2,final_score=90) for i in range(20)])
        with CaptureQueriesContext(connection) as q1:self.read(pageSize=1)
        with CaptureQueriesContext(connection) as q2:self.read(pageSize=20)
        self.assertLessEqual(len(q2),len(q1)+1)

    def test_bad_offer_inputs_do_not_make_draft(self):
        for kwargs in ({'expires_in_days':0},{'expires_in_days':True},{'expires_in_days':'1.5'},{'expected_report_date':'no-date'}):
            with self.assertRaises(OfferServiceError):
                self.offer_service.create_offer(proposed_hire_id=self.proposed.id,offer_no=uuid4().hex,**kwargs)
        self.assertEqual(HrRecruitmentOffer.objects.count(),1)
