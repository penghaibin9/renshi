"""MySQL and real-login contracts for an empty school's initial HR02 structure."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch

from auditlog.models import LogEntry
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import close_old_connections, connections
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from base.models import Company, CompanyGroupAssignment
from employee.models import Employee
from horilla.horilla_middlewares import tenant_context
from hr_staff.models import HrOutboxEvent, HrStaffMaster
from hr_structure.initialization_forms import InitialStructureForm
from hr_structure.initialization_views import setup_proof
from hr_structure.models import (
    HrOrganization, HrOrganizationRelation, HrOrganizationVersion, HrPosition,
    HrPositionVersion, HrPostCatalog, HrPostCatalogVersion, HrSchoolStructureInitialization,
)
from hr_structure.selectors.organization import OrganizationSelector
from hr_structure.scope import Hr02Scope
from hr_structure.services.initialization import (
    SETUP_PERMISSIONS, StructureSetupConflict, initialize_structure,
)

SETTINGS = dict(COMPANY_SCOPED_PERMISSIONS=True, TENANT_FAIL_CLOSED=True,
                ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"])
DATA = dict(root_code="SCH", department_code="OFFICE", department_name="教务处",
            department_type="OFFICE", catalog_code="ACADEMIC", catalog_name="教务管理岗",
            category="MANAGEMENT", position_code="ACADEMIC-001", planned_fte="1.00",
            confirmed="on")
MODELS = (HrOrganization, HrOrganizationVersion, HrOrganizationRelation, HrPostCatalog,
          HrPostCatalogVersion, HrPosition, HrPositionVersion, HrSchoolStructureInitialization)


def school(name):
    return Company.objects.create(company=name, address="学校路 1 号", country="CN",
                                  state="Hunan", city="Changsha", zip="410000")


def member(company, name, *, manage=True):
    user = get_user_model().objects.create_user(username=name, password="isolated-school-setup-test")
    user.is_new_employee = False
    user.save(update_fields=["is_new_employee"])
    codes = SETUP_PERMISSIONS if manage else tuple(code for code in SETUP_PERMISSIONS if code.endswith(".view"))
    permissions = list(Permission.objects.filter(codename__in=codes))
    if {item.codename for item in permissions} != set(codes):
        raise AssertionError("Canonical HR02 permissions are missing")
    permissions.append(Permission.objects.get(content_type__app_label="base", codename="view_company"))
    group = Group.objects.create(name=name)
    group.permissions.set(permissions)
    CompanyGroupAssignment.objects.create(user=user, company=company, group=group)
    CompanyGroupAssignment.sync_user_group_membership(user, group)
    return user


class Fixture:
    def setUp(self):
        self.school = school("首次建组织学校 A")
        self.other = school("首次建组织学校 B")
        self.admin = member(self.school, "structure-admin")
        self.viewer = member(self.school, "structure-viewer", manage=False)
        self.other_admin = member(self.other, "structure-other")
        self.today = timezone.localdate()

    def command(self, **changes):
        with tenant_context(self.school.pk):
            return initialize_structure(
                tenant_id=self.school.pk, actor=self.admin, values={**DATA, **changes},
                expected_school_name=self.school.company, effective_date=self.today,
            )

    def counts(self):
        return [model.objects.filter(tenant_id=self.school.pk).count() for model in MODELS]

    def login(self, user):
        browser = Client(enforce_csrf_checks=True)
        self.assertEqual(browser.get("/login/").status_code, 200)
        response = browser.post("/login/?next=" + reverse("hr-structure-initial-setup"),
                                {"username": user.username, "password": "isolated-school-setup-test"},
                                HTTP_X_CSRFTOKEN=browser.cookies["csrftoken"].value)
        self.assertEqual(response.status_code, 302)
        return browser


@override_settings(**SETTINGS)
class InitialStructureTests(Fixture, TestCase):
    def test_single_transaction_builds_real_history_outbox_and_actor_audit(self):
        receipt, created = self.command()
        self.assertTrue(created)
        self.assertEqual(self.counts(), [2, 2, 1, 1, 1, 1, 1, 1])
        selector = OrganizationSelector(Hr02Scope("SCHOOL", self.school.pk), self.today)
        self.assertEqual(selector.get_root().name, self.school.company)
        self.assertEqual(selector.get_children(receipt.root_version.organization_id_id).get().name, "教务处")
        self.assertEqual(receipt.position.organization_id_id, receipt.department_version.organization_id_id)
        self.assertEqual(receipt.position.lifecycle_status, "ACTIVE")
        events = HrOutboxEvent.objects.filter(tenant_id=self.school.pk)
        self.assertEqual(events.count(), 3)
        self.assertEqual(set(events.values_list("event_type", flat=True)),
                         {"hr.structure.organization.created", "hr.structure.position.created"})
        audit = LogEntry.objects.get(additional_data__source="hr02_initial_structure")
        self.assertEqual(audit.actor_id, self.admin.pk)
        self.assertEqual(audit.additional_data["tenant_id"], self.school.pk)
        self.assertEqual(audit.additional_data["position_id"], receipt.position_id)
        self.assertFalse(Employee.objects.exists())
        self.assertFalse(HrStaffMaster.objects.exists())
        self.assertFalse(HrOrganization.objects.filter(tenant_id=self.other.pk).exists())

    def test_same_payload_retry_returns_receipt_without_extra_events(self):
        first, _ = self.command()
        again, created = self.command(planned_fte="1")
        self.assertFalse(created)
        self.assertEqual(again.pk, first.pk)
        self.assertEqual(self.counts(), [2, 2, 1, 1, 1, 1, 1, 1])
        self.assertEqual(HrOutboxEvent.objects.filter(tenant_id=self.school.pk).count(), 3)
        self.assertEqual(LogEntry.objects.filter(additional_data__source="hr02_initial_structure").count(), 1)

    def test_conflicting_retry_does_not_overwrite(self):
        self.command()
        with self.assertRaises(StructureSetupConflict):
            self.command(department_name="不能改为第二个部门")
        self.assertEqual(HrOrganizationVersion.objects.get(tenant_id=self.school.pk, org_type="OFFICE").name, "教务处")

    def test_existing_structure_even_draft_is_not_reset(self):
        HrOrganization.objects.create(tenant_id=self.school.pk, stable_code="EXISTING")
        with self.assertRaises(StructureSetupConflict):
            self.command()
        self.assertEqual(self.counts(), [1, 0, 0, 0, 0, 0, 0, 0])

    def test_incomplete_profile_is_rejected(self):
        Company.objects.filter(pk=self.school.pk).update(address="")
        with self.assertRaises(StructureSetupConflict):
            self.command()
        self.assertEqual(self.counts(), [0] * len(MODELS))

    def test_confirmation_and_payload_validation_are_not_browser_only(self):
        for change in ({"confirmed": ""}, {"planned_fte": "NaN"}, {"planned_fte": "0"},
                       {"planned_fte": "2"}, {"root_code": "x" * 65}, {"category": "UNKNOWN"},
                       {"department_code": "sch"}, {"department_name": " "}):
            with self.subTest(change=change), self.assertRaises(ValidationError):
                self.command(**change)
        self.assertEqual(self.counts(), [0] * len(MODELS))

    def test_service_failure_rolls_back_all_earlier_objects_then_retry_succeeds(self):
        with patch("hr_structure.services.initialization.PositionService.create_position", side_effect=RuntimeError("injected failure")):
            with self.assertRaises(RuntimeError):
                self.command()
        self.assertEqual(self.counts(), [0] * len(MODELS))
        self.assertFalse(HrOutboxEvent.objects.filter(tenant_id=self.school.pk).exists())
        self.assertTrue(self.command()[1])

    def test_audit_failure_rolls_back_receipt_history_and_events(self):
        with patch("hr_structure.services.initialization.LogEntry.objects.log_create", side_effect=RuntimeError("audit unavailable")):
            with self.assertRaises(RuntimeError):
                self.command()
        self.assertEqual(self.counts(), [0] * len(MODELS))
        self.assertFalse(HrOutboxEvent.objects.filter(tenant_id=self.school.pk).exists())

    def test_each_write_permission_is_required(self):
        group = self.admin.company_group_assignments.get().group
        for code in ("hr.structure.organization.create", "hr.structure.post_catalog.manage", "hr.structure.position.manage"):
            permission = Permission.objects.get(codename=code)
            group.permissions.remove(permission)
            with self.subTest(code=code), self.assertRaises(PermissionDenied):
                self.command()
            group.permissions.add(permission)

    def test_actor_cannot_change_school_in_service_call(self):
        with tenant_context(self.other.pk), self.assertRaises(PermissionDenied):
            initialize_structure(tenant_id=self.other.pk, actor=self.admin, values=DATA,
                                 expected_school_name=self.other.company, effective_date=self.today)
        self.assertEqual(self.counts(), [0] * len(MODELS))

    def test_real_login_get_is_read_only_and_post_reloads_receipt(self):
        browser = self.login(self.admin)
        response = browser.get(reverse("hr-structure-initial-setup"))
        self.assertContains(response, 'id="initial-structure-form"')
        self.assertEqual(self.counts(), [0] * len(MODELS))
        proof = response.context["setup_proof"]
        response = browser.post(reverse("hr-structure-initial-setup"), {**DATA, "setup_proof": proof},
                                HTTP_X_CSRFTOKEN=browser.cookies["csrftoken"].value)
        self.assertEqual(response.status_code, 302)
        page = browser.get(response["Location"])
        self.assertContains(page, 'id="structure-setup-receipt"')
        self.assertContains(page, "教务处")
        self.assertNotContains(page, self.other.company)

    def test_readonly_can_read_receipt_but_cannot_initialize(self):
        self.command()
        browser = self.login(self.viewer)
        self.assertContains(browser.get(reverse("hr-structure-initial-setup")), 'id="structure-setup-receipt"')
        response = browser.post(reverse("hr-structure-initial-setup"), DATA,
                                HTTP_X_CSRFTOKEN=browser.cookies["csrftoken"].value)
        self.assertEqual(response.status_code, 403)

    def test_csrf_and_other_school_proof_rejected_before_write(self):
        browser = self.login(self.admin)
        self.assertEqual(browser.post(reverse("hr-structure-initial-setup"), DATA).status_code, 403)
        response = browser.post(reverse("hr-structure-initial-setup"),
                                {**DATA, "setup_proof": setup_proof(self.other_admin, self.other)},
                                HTTP_X_CSRFTOKEN=browser.cookies["csrftoken"].value)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.counts(), [0] * len(MODELS))

    def test_changed_school_name_after_form_open_requires_recheck(self):
        browser = self.login(self.admin)
        proof = browser.get(reverse("hr-structure-initial-setup")).context["setup_proof"]
        Company.objects.filter(pk=self.school.pk).update(company="已更名学校")
        response = browser.post(reverse("hr-structure-initial-setup"), {**DATA, "setup_proof": proof},
                                HTTP_X_CSRFTOKEN=browser.cookies["csrftoken"].value)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.counts(), [0] * len(MODELS))

    def test_expired_proof_returns_409_without_half_written_data(self):
        browser = self.login(self.admin)
        original_loads = signing.loads

        def expire_setup_proof(*args, **kwargs):
            if kwargs.get("salt") == "hr02.initial-structure.v1":
                raise signing.SignatureExpired("expired")
            return original_loads(*args, **kwargs)

        with patch("hr_structure.initialization_views.signing.loads", side_effect=expire_setup_proof):
            response = browser.post(reverse("hr-structure-initial-setup"), {**DATA, "setup_proof": "expired"},
                                    HTTP_X_CSRFTOKEN=browser.cookies["csrftoken"].value)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.counts(), [0] * len(MODELS))

    def test_field_names_do_not_collide_with_global_form_scripts(self):
        form = InitialStructureForm()
        for field in form:
            self.assertTrue(field.id_for_label.startswith("structure-setup-"))


@override_settings(**SETTINGS)
class InitialStructureConcurrencyTests(Fixture, TransactionTestCase):
    def test_two_simultaneous_commands_create_exactly_one_structure(self):
        barrier = Barrier(2)
        school_id, actor_id, name, today = self.school.pk, self.admin.pk, self.school.company, self.today

        def submit(_):
            close_old_connections()
            try:
                actor = get_user_model().objects.get(pk=actor_id)
                with tenant_context(school_id):
                    barrier.wait(timeout=15)
                    receipt, created = initialize_structure(
                        tenant_id=school_id, actor=actor, values=DATA,
                        expected_school_name=name, effective_date=today,
                    )
                    return receipt.pk, created
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(submit, range(2)))
        self.assertEqual(len({row[0] for row in results}), 1)
        self.assertEqual(sum(row[1] for row in results), 1)
        self.assertEqual(self.counts(), [2, 2, 1, 1, 1, 1, 1, 1])
        self.assertEqual(HrOutboxEvent.objects.filter(tenant_id=school_id).count(), 3)
