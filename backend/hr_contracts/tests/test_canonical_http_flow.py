from datetime import date, timedelta
from unittest import skipUnless
from unittest.mock import patch

from django.apps import apps
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from hr_contracts.models import (
    HrContractAgreement,
    HrContractCase,
    HrContractExpiryPolicy,
    HrContractTemplateVersion,
    HrContractVersion,
)
from hr_contracts.events import (
    EVENT_AGREEMENT_CREATED,
    EVENT_AGREEMENT_EFFECTIVE,
    EVENT_AGREEMENT_SIGNED,
)
from hr_contracts.services.agreement_service import AgreementService
from hr_staff.models import HrOutboxEvent
from hr_staff.models import HrEmploymentRelationship, HrPerson, HrStaffMaster


LEGACY_HTTP_CONTEXT_AVAILABLE = apps.is_installed("base") and apps.is_installed(
    "employee"
)
if LEGACY_HTTP_CONTEXT_AVAILABLE:
    from base.models import Company
    from employee.models import Employee, EmployeeWorkInformation


@skipUnless(
    LEGACY_HTTP_CONTEXT_AVAILABLE,
    "requires the complete MySQL Horilla CompanyMiddleware integration runtime",
)
class Hr07CanonicalHttpFlowTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(company="HR07 权威测试学校", hq=True)
        self.other_company = Company.objects.create(company="HR07 其他学校", hq=False)
        self.user = get_user_model().objects.create_superuser(
            username="hr07-http-auditor",
            email="hr07-http@example.invalid",
            password="test-only-password",
        )
        employee = Employee.objects.create(
            employee_user_id=self.user,
            employee_first_name="HR07",
            employee_last_name="验收员",
            email="hr07-employee@example.invalid",
            phone="13800007001",
            is_active=True,
        )
        work_info, _ = EmployeeWorkInformation._base_manager.get_or_create(
            employee_id=employee
        )
        work_info.company_id = self.company
        work_info.save(update_fields=["company_id"])
        self.client.force_login(self.user)
        session = self.client.session
        session["selected_company"] = str(self.company.pk)
        session.save()

        person = HrPerson.objects.create(
            tenant_id=self.company.pk,
            legal_name="陈雨桐",
            status="ACTIVE",
        )
        self.staff = HrStaffMaster.objects.create(
            tenant_id=self.company.pk,
            person_id=person,
            staff_no="T-07001",
            current_employment_status="ACTIVE",
        )
        self.relationship = HrEmploymentRelationship.objects.create(
            tenant_id=self.company.pk,
            staff_id=self.staff,
            relationship_type="REGULAR_EMPLOYMENT",
            employment_type="PUBLIC_INSTITUTION",
            effective_from=date(2025, 9, 1),
            status="ACTIVE",
        )

    def post_json(self, path, payload):
        return self.client.post(path, payload, content_type="application/json")

    def test_agreement_list_resolves_hr03_labels_and_stays_tenant_scoped(self):
        own = HrContractAgreement.objects.create(
            tenant_id=self.company.pk,
            agreement_no="HT-OWN-001",
            staff_id=self.staff.id,
            employment_relationship_id=self.relationship.id,
            agreement_title="校内聘用合同",
            agreement_type="FIXED_TERM",
        )
        HrContractAgreement.objects.create(
            tenant_id=self.other_company.pk,
            agreement_no="HT-OTHER-001",
            staff_id=self.staff.id,
            employment_relationship_id=self.relationship.id,
            agreement_title="其他学校合同",
            agreement_type="FIXED_TERM",
        )

        response = self.client.get("/api/v1/hr/contracts/agreements?limit=100")

        self.assertEqual(response.status_code, 200)
        rows = response.json()["data"]
        self.assertEqual([row["id"] for row in rows], [str(own.id)])
        self.assertEqual(rows[0]["staffName"], "陈雨桐")
        self.assertEqual(rows[0]["staffNo"], "T-07001")
        self.assertEqual(rows[0]["relationshipType"], "REGULAR_EMPLOYMENT")

    def test_real_http_flow_keeps_versions_append_only_and_cases_resumable(self):
        today = timezone.localdate()
        created = self.post_json(
            "/api/v1/hr/contracts/agreements",
            {
                "agreementNo": "HT-2026-07001",
                "staffId": str(self.staff.id),
                "employmentRelationshipId": str(self.relationship.id),
                "title": "专任教师聘用合同",
                "agreementType": "FIXED_TERM",
            },
        )
        self.assertEqual(created.status_code, 201, created.content)
        agreement_id = created.json()["data"]["id"]

        signed = self.post_json(
            f"/api/v1/hr/contracts/agreements/{agreement_id}/versions/sign",
            {
                "effectiveFrom": today.isoformat(),
                "effectiveTo": (today + timedelta(days=365)).isoformat(),
                "signedAt": timezone.now().isoformat(),
                "signedDocumentRef": "ESIGN-INITIAL-07001",
                "contentSnapshot": {"summary": "首版正式条款"},
            },
        )
        self.assertEqual(signed.status_code, 201, signed.content)
        initial_version_id = signed.json()["data"]["versionId"]
        activated = self.post_json(
            f"/api/v1/hr/contracts/agreements/{agreement_id}/versions/{initial_version_id}/activate",
            {"asOf": today.isoformat()},
        )
        self.assertEqual(activated.status_code, 200, activated.content)

        case_created = self.post_json(
            "/api/v1/hr/contracts/cases",
            {
                "caseNo": "RENEW-2026-07001",
                "agreementId": agreement_id,
                "caseType": "RENEW",
                "requestedEffectiveFrom": (today + timedelta(days=365)).isoformat(),
                "requestedEffectiveTo": (today + timedelta(days=730)).isoformat(),
                "reasonCode": "NORMAL_RENEWAL",
                "reasonText": "聘期届满续签",
            },
        )
        self.assertEqual(case_created.status_code, 201, case_created.content)
        case_id = case_created.json()["data"]["id"]

        for action, expected in (("submit", "SUBMITTED"), ("approve", "APPROVED")):
            response = self.post_json(
                f"/api/v1/hr/contracts/cases/{case_id}/{action}", {}
            )
            self.assertEqual(response.status_code, 200, response.content)
            self.assertEqual(response.json()["data"]["status"], expected)

        successor = self.post_json(
            f"/api/v1/hr/contracts/cases/{case_id}/versions/sign",
            {
                "signedAt": timezone.now().isoformat(),
                "signedDocumentRef": "ESIGN-RENEW-07001",
                "contentSnapshot": {"summary": "续签正式条款"},
            },
        )
        self.assertEqual(successor.status_code, 201, successor.content)
        successor_id = successor.json()["data"]["id"]

        resumed = self.client.get(f"/api/v1/hr/contracts/cases/{case_id}")
        self.assertEqual(resumed.status_code, 200, resumed.content)
        self.assertEqual(resumed.json()["data"]["status"], "EFFECT_PENDING")
        self.assertEqual(
            resumed.json()["data"]["successorVersion"]["id"], successor_id
        )

        effected = self.post_json(
            f"/api/v1/hr/contracts/cases/{case_id}/versions/{successor_id}/activate",
            {"asOf": (today + timedelta(days=365)).isoformat()},
        )
        self.assertEqual(effected.status_code, 200, effected.content)
        self.assertEqual(effected.json()["data"]["status"], "EFFECTIVE")

        agreement = HrContractAgreement.objects.get(id=agreement_id)
        case = HrContractCase.objects.get(id=case_id)
        versions = list(
            HrContractVersion.objects.filter(agreement=agreement).order_by("version_no")
        )
        self.assertEqual(agreement.status, "ACTIVE")
        self.assertEqual(case.status, "EFFECTIVE")
        self.assertEqual([item.version_no for item in versions], [1, 2])
        self.assertEqual(versions[0].status, "SUPERSEDED")
        self.assertEqual(versions[1].status, "EFFECTIVE")
        self.assertEqual(
            HrOutboxEvent.objects.filter(
                tenant_id=self.company.pk, event_type=EVENT_AGREEMENT_CREATED
            ).count(),
            1,
        )
        self.assertEqual(
            HrOutboxEvent.objects.filter(
                tenant_id=self.company.pk, event_type=EVENT_AGREEMENT_SIGNED
            ).count(),
            2,
        )
        self.assertEqual(
            HrOutboxEvent.objects.filter(
                tenant_id=self.company.pk, event_type=EVENT_AGREEMENT_EFFECTIVE
            ).count(),
            2,
        )

        collection = self.client.get("/api/v1/hr/contracts/cases?limit=100")
        self.assertEqual(collection.status_code, 200)
        self.assertEqual(collection.json()["data"][0]["caseNo"], "RENEW-2026-07001")

    def test_case_detail_never_crosses_selected_school(self):
        other = HrContractAgreement.objects.create(
            tenant_id=self.other_company.pk,
            agreement_no="HT-OTHER-CASE",
            staff_id=self.staff.id,
            employment_relationship_id=self.relationship.id,
            agreement_title="不可见合同",
            agreement_type="OTHER",
            status="ACTIVE",
            current_version_no=1,
        )
        other_case = HrContractCase.objects.create(
            tenant_id=self.other_company.pk,
            case_no="CASE-OTHER-001",
            agreement=other,
            case_type="CHANGE",
            status="DRAFT",
            requested_effective_from=date.today(),
        )

        response = self.client.get(f"/api/v1/hr/contracts/cases/{other_case.id}")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "CONTRACT_CASE_NOT_FOUND")

    def test_external_workforce_agreement_uses_person_label_without_fake_staff(self):
        external_person = HrPerson.objects.create(
            tenant_id=self.company.pk,
            legal_name="外聘专家周岚",
            status="ACTIVE",
        )
        agreement = AgreementService(
            self.company.pk, self.user.pk
        ).create_external_agreement(
            agreement_no="EXT-2026-07001",
            person_id=external_person.id,
            subject_reference_type="HR08_HIRING_CASE",
            subject_reference_id="hiring-case-07001",
            agreement_title="外聘专家合作协议",
            agreement_type="EXTERNAL_TEACHER",
        )

        response = self.client.get(
            f"/api/v1/hr/contracts/agreements/{agreement.id}"
        )

        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()["data"]
        self.assertEqual(data["subjectType"], "EXTERNAL_WORKFORCE")
        self.assertEqual(data["staffName"], "外聘专家周岚")
        self.assertIsNone(data["staffId"])
        self.assertIsNone(data["employmentRelationshipId"])
        event = HrOutboxEvent.objects.get(
            tenant_id=self.company.pk,
            event_type=EVENT_AGREEMENT_CREATED,
            payload_json__agreementId=str(agreement.id),
        )
        self.assertNotIn("staffId", event.payload_json)
        self.assertEqual(
            event.payload_json["subjectPersonId"], str(external_person.id)
        )

    def test_outbox_failure_rolls_back_formal_signing_fact(self):
        agreement = HrContractAgreement.objects.create(
            tenant_id=self.company.pk,
            agreement_no="HT-OUTBOX-ROLLBACK",
            staff_id=self.staff.id,
            employment_relationship_id=self.relationship.id,
            agreement_title="Outbox 回滚合同",
            agreement_type="FIXED_TERM",
        )

        with patch(
            "hr_contracts.services.agreement_service.emit_registered_event",
            side_effect=RuntimeError("outbox unavailable"),
        ):
            with self.assertRaises(RuntimeError):
                AgreementService(self.company.pk, self.user.pk).sign_initial_version(
                    agreement_id=agreement.id,
                    effective_from=date.today(),
                    effective_to=date.today() + timedelta(days=365),
                    signed_at=timezone.now(),
                    signed_document_ref="ESIGN-ROLLBACK",
                    content_snapshot={"summary": "不得留下半成品"},
                )

        agreement.refresh_from_db()
        self.assertEqual(agreement.status, "DRAFT")
        self.assertEqual(agreement.current_version_no, 0)
        self.assertFalse(HrContractVersion.objects.filter(agreement=agreement).exists())

    def test_setup_api_publishes_immutable_template_versions_and_one_active_policy(self):
        today = timezone.localdate()
        first = self.post_json(
            "/api/v1/hr/contracts/setup/templates/publish",
            {
                "templateCode": "TEACHER_FIXED",
                "templateName": "专任教师合同",
                "agreementType": "FIXED_TERM",
                "numberingPrefix": "HT-JS",
                "defaultTermMonths": 36,
                "effectiveFrom": today.isoformat(),
                "bodyTemplate": "〔姓名〕与学校签订本合同。",
            },
        )
        second = self.post_json(
            "/api/v1/hr/contracts/setup/templates/publish",
            {
                "templateCode": "TEACHER_FIXED",
                "templateName": "专任教师合同（修订）",
                "agreementType": "FIXED_TERM",
                "numberingPrefix": "HT-JS",
                "defaultTermMonths": 48,
                "effectiveFrom": today.isoformat(),
                "bodyTemplate": "〔姓名〕与学校签订修订版合同。",
            },
        )
        self.assertEqual(first.status_code, 201, first.content)
        self.assertEqual(second.status_code, 201, second.content)
        versions = list(
            HrContractTemplateVersion.objects.filter(
                tenant_id=self.company.pk, template_code="TEACHER_FIXED"
            ).order_by("version_no")
        )
        self.assertEqual([row.version_no for row in versions], [1, 2])
        self.assertEqual([row.status for row in versions], ["RETIRED", "PUBLISHED"])
        self.assertEqual(len(versions[1].content_hash), 64)

        for version, warning in (("EXP-V1", 60), ("EXP-V2", 90)):
            response = self.post_json(
                "/api/v1/hr/contracts/setup/expiry-policies/publish",
                {
                    "policyVersion": version,
                    "agreementType": "FIXED_TERM",
                    "warningDays": warning,
                    "criticalAfterDays": 30,
                    "actionType": "CREATE_RENEWAL_CASE",
                },
            )
            self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(
            HrContractExpiryPolicy.objects.filter(
                tenant_id=self.company.pk,
                agreement_type="FIXED_TERM",
                active=True,
            ).count(),
            1,
        )

        workbench = self.client.get("/api/v1/hr/contracts/setup/workbench")
        self.assertEqual(workbench.status_code, 200, workbench.content)
        self.assertEqual(len(workbench.json()["data"]["templates"]), 2)
        self.assertEqual(len(workbench.json()["data"]["expiryPolicies"]), 2)
