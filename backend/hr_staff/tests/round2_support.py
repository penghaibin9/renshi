"""Real-ORM fixtures. Must run on a disposable MySQL database, never SQLite.
The inert text fixture is explicitly marked scanned; this is NOT scanner E2E.
No application authority service, outbox emitter, or database is mocked here.
"""
import tempfile
import uuid
from datetime import date
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import TestCase, override_settings
from base.models import Company
from hr_staff.models import HrPerson, HrStaffMaster, HrEmploymentRelationship
from hr_staff.services.authority_mode_service import AuthorityModeService
from hr_staff.services.material_file_service import store_staff_material
from hr_staff.services.material_service import MaterialService
from hr_self.services.identity_service import SelfIdentityContext

class MySQLRound2Case(TestCase):
    @classmethod
    def setUpClass(cls):
        if connection.vendor != "mysql":
            raise AssertionError("ROUND2_REQUIRES_MYSQL: SQLite is not an acceptance substitute")
        super().setUpClass()

    def setUp(self):
        super().setUp()
        directory = tempfile.TemporaryDirectory(prefix="hr-round2-fixture-")
        self.addCleanup(directory.cleanup)
        settings = override_settings(MEDIA_ROOT=directory.name, MALWARE_SCAN_REQUIRED=True)
        settings.enable()
        self.addCleanup(settings.disable)
        self.company = Company.objects.create(company="Round2 isolated fixture school")
        self.tenant = self.company.pk
        self.user = get_user_model().objects.create_user(username="r2-staff-"+uuid.uuid4().hex)
        self.reviewer = get_user_model().objects.create_user(username="r2-reviewer-"+uuid.uuid4().hex)
        self.person = HrPerson.objects.create(tenant_id=self.tenant, legal_name="Fixture staff",
            gender_code="M", birth_date=date(1966,6,1))
        self.staff = HrStaffMaster.objects.create(tenant_id=self.tenant, person_id=self.person,
            staff_no="R2-001", staff_category_code="TEACHER")
        self.relationship = HrEmploymentRelationship.objects.create(tenant_id=self.tenant,
            staff_id=self.staff, relationship_type="REGULAR_EMPLOYMENT",
            effective_from=date(1990,9,1), status="ACTIVE")
        AuthorityModeService().record_cutover(tenant_id=self.tenant, mode="HR03_AUTHORITY",
            reason="Isolated MySQL integration fixture, not a production cutover")
        self.context = SelfIdentityContext(self.tenant,self.user.pk,self.staff.id,self.person.id,0)

    def evidence(self, text="inert human-resources test evidence", category="CORRECTION_EVIDENCE"):
        upload=SimpleUploadedFile("proof.txt", text.encode(), content_type="text/plain")
        upload._malware_scan_complete=True  # trusted inert fixture only, never production requests
        metadata=store_staff_material(upload,tenant_id=self.tenant,staff_id=self.staff.id)
        material=MaterialService(self.tenant,self.user.pk).create_material(staff_id=self.staff.id,
            category_code=category,title="Fixture evidence",sensitivity_level="SENSITIVE",**metadata)
        from hr_staff.models import HrStaffMaterialVersion
        return HrStaffMaterialVersion.objects.get(pk=material.current_version_id)
