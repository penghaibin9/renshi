from datetime import date
from unittest.mock import patch
from django.db import connection, DatabaseError, transaction
from hr_staff.tests.round2_support import MySQLRound2Case
from hr_exit.models import RetirementFact, ExitCase
from hr_exit.flex_models import RetirementFlexApplication, RetirementFlexEvent
from hr_exit.services.flex_service import FlexRetirementService, FlexError, validate_retirement_effect
from hr_exit.services.retirement_policy_service import RetirementPolicyService, RetirementPrecheckService

class FlexibleRetirementMySQLTests(MySQLRound2Case):
    def setUp(self):
        super().setUp()
        clock=patch("django.utils.timezone.localdate",return_value=date(2026,2,1))
        clock.start();self.addCleanup(clock.stop)
        service=RetirementPolicyService(self.tenant,self.reviewer.pk)
        policy=service.create_draft(policy_code="R2-ORDINARY-M",retirement_type="STATUTORY",
            retirement_age_months=720,effective_from=date(2025,1,1),gender_code="M",
            staff_category_code="TEACHER",relationship_type="REGULAR_EMPLOYMENT",
            transition_birth_start=date(1965,1,1),delay_step_birth_months=4,
            max_retirement_age_months=756,rationale="Sealed ordinary-cohort fixture")
        service.activate(policy.id)
        self.precheck=RetirementPrecheckService(self.tenant,self.user.pk).evaluate(
            person_id=self.person.id,employment_relationship_id=self.relationship.id,
            as_of=date(2026,2,1),idempotency_key="r2-precheck-001").precheck
        self.notice=self.evidence("retirement notice", "RETIREMENT_NOTICE")
        self.approval=self.evidence("retirement approval", "RETIREMENT_APPROVAL")
        self.contribution=self.evidence("retirement contribution", "RETIREMENT_CONTRIBUTION")
        self.agreement=self.evidence("retirement agreement", "RETIREMENT_AGREEMENT")
        self.service=FlexRetirementService(self.tenant,self.user.pk)
        self.manager=FlexRetirementService(self.tenant,self.reviewer.pk)

    def create(self,key="r2-flex-001"):
        return self.service.create(staff_id=self.staff.id,precheck_id=self.precheck.id,
            mode="DELAY",requested_date="2027-05-01",reason="Voluntary delay fixture",idempotency_key=key)
    def submit(self):
        app,_=self.create()
        return self.service.submit(app.id,staff_id=self.staff.id,expected_version=app.version,
            notice_version_id=self.notice.id)
    def review_data(self,capacity="PUBLIC_TECHNICAL"):
        return {"capacity":capacity,"contributionMonths":360,"agreementDate":"2026-02-01",
            "approvalMaterialVersionId":str(self.approval.id),"contributionMaterialVersionId":str(self.contribution.id),
            "agreementMaterialVersionId":str(self.agreement.id)}
    def approve(self,app):
        return self.manager.review(app.id,expected_version=app.version,action="APPROVE",
            reason="Independent personnel review",review=self.review_data())

    def test_notice_approval_links_existing_exit_without_retiring_immediately(self):
        app=self.approve(self.submit())
        self.assertTrue(app.verify_seal())
        app=self.manager.open_exit_case(app.id,expected_version=app.version)
        case=ExitCase.objects.get(tenant_id=self.tenant,pk=app.exit_case_id)
        self.assertEqual(case.status,"DRAFT")
        self.assertEqual(case.planned_employment_end_date,date(2027,5,1))
        self.assertFalse(RetirementFact.objects.filter(tenant_id=self.tenant,person_id=self.person.id).exists())
        self.relationship.refresh_from_db();self.assertEqual(self.relationship.status,"ACTIVE")
        self.assertEqual(RetirementFlexEvent.objects.filter(application_id=app.id).count(),4)

    def test_same_command_replays_one_application(self):
        a,created=self.create();b,replayed=self.create()
        self.assertTrue(created);self.assertFalse(replayed);self.assertEqual(a.pk,b.pk)
        self.assertEqual(RetirementFlexEvent.objects.filter(application_id=a.id).count(),1)

    def test_same_key_different_payload_is_conflict(self):
        self.create()
        with self.assertRaises(FlexError) as error:
            self.service.create(staff_id=self.staff.id,precheck_id=self.precheck.id,mode="DELAY",
                requested_date="2027-06-01",reason="changed",idempotency_key="r2-flex-001")
        self.assertEqual(error.exception.code,"FLEX_IDEMPOTENCY_CONFLICT")

    def test_notice_category_is_mandatory(self):
        app,_=self.create("r2-wrong-notice")
        wrong=self.evidence("generic evidence", "OTHER_HR")
        with self.assertRaises(FlexError) as error:
            self.service.submit(app.id,staff_id=self.staff.id,expected_version=app.version,
                notice_version_id=wrong.id)
        self.assertEqual(error.exception.code,"FLEX_EVIDENCE_CATEGORY_MISMATCH")

    def test_approval_evidence_cannot_reuse_one_material(self):
        app=self.submit()
        review=self.review_data()
        review["contributionMaterialVersionId"]=review["approvalMaterialVersionId"]
        with self.assertRaises(FlexError) as error:
            self.manager.review(app.id,expected_version=app.version,action="APPROVE",
                reason="review",review=review)
        self.assertEqual(error.exception.code,"FLEX_EVIDENCE_CATEGORY_MISMATCH")

    def test_approval_verifies_exact_selected_versions(self):
        app=self.approve(self.submit())
        for version in (self.notice,self.approval,self.contribution,self.agreement):
            version.refresh_from_db()
            self.assertEqual(version.verified_by,self.reviewer.pk)
            self.assertIsNotNone(version.verified_at)
        self.assertEqual(app.review_snapshot["approvalEvidence"]["categoryCode"],"RETIREMENT_APPROVAL")
        self.assertEqual(app.review_snapshot["contributionEvidence"]["categoryCode"],"RETIREMENT_CONTRIBUTION")
        self.assertEqual(app.review_snapshot["agreementEvidence"]["categoryCode"],"RETIREMENT_AGREEMENT")

    def test_self_approval_is_forbidden(self):
        app=self.submit()
        with self.assertRaises(FlexError) as error:
            self.service.review(app.id,expected_version=app.version,action="APPROVE",reason="self",review=self.review_data())
        self.assertEqual(error.exception.status,403)

    def test_excluded_public_management_cannot_be_approved(self):
        app=self.submit()
        with self.assertRaises(FlexError):
            self.manager.review(app.id,expected_version=app.version,action="APPROVE",reason="review",
                review=self.review_data("PUBLIC_MANAGEMENT"))
        app.refresh_from_db();self.assertEqual(app.status,"SUBMITTED")

    def test_stale_version_cannot_return_a_case(self):
        app=self.submit()
        with self.assertRaises(FlexError) as error:
            self.manager.review(app.id,expected_version=1,action="RETURN",reason="supplement")
        self.assertEqual(error.exception.code,"FLEX_VERSION_CONFLICT")

    def test_other_school_cannot_review(self):
        app=self.submit()
        with self.assertRaises(FlexError) as error:
            FlexRetirementService(self.tenant+100000,self.reviewer.pk).review(app.id,
                expected_version=app.version,action="RETURN",reason="invalid school")
        self.assertEqual(error.exception.status,404)

    def test_future_retirement_cannot_end_employment(self):
        app=self.approve(self.submit());app=self.manager.open_exit_case(app.id,expected_version=app.version)
        case=ExitCase.objects.get(pk=app.exit_case_id)
        with self.assertRaises(FlexError) as error: validate_retirement_effect(self.tenant,case)
        self.assertEqual(error.exception.code,"RETIREMENT_EFFECT_NOT_DUE")

    def test_approved_application_is_sealed_in_mysql(self):
        app=self.approve(self.submit())
        with self.assertRaises(DatabaseError),transaction.atomic(),connection.cursor() as cursor:
            cursor.execute("UPDATE hr16_retirement_flex_application SET requested_date=%s WHERE id=%s",
                [date(2027,6,1),app.id.hex])
        app.refresh_from_db();self.assertEqual(app.requested_date,date(2027,5,1))

    def test_approved_delay_cannot_be_extended_by_second_application(self):
        self.approve(self.submit())
        with self.assertRaises(FlexError) as error: self.create("r2-second-delay")
        self.assertEqual(error.exception.code,"FLEX_ALREADY_OPEN")
