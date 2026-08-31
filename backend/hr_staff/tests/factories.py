"""HR03 测试工厂（S3 起复用）。"""

from datetime import date

from hr_structure.models import HrOrganization, HrOrganizationVersion

from hr_staff.models import HrPerson, HrStaffMaster
from hr_staff.services.staff_master_service import StaffMasterService


def make_person(tenant_id: int, legal_name: str) -> HrPerson:
    return HrPerson.objects.create(tenant_id=tenant_id, legal_name=legal_name)


def make_staff(tenant_id: int, person: HrPerson, staff_no: str) -> HrStaffMaster:
    return StaffMasterService().create_staff(
        tenant_id=tenant_id,
        person_id=person,
        staff_no=staff_no,
    )


def make_org(tenant_id: int, stable_code: str, name: str, validity_from: date, validity_to=None, org_type="COLLEGE") -> HrOrganization:
    org = HrOrganization.objects.create(
        tenant_id=tenant_id,
        stable_code=stable_code,
        org_dimension="ADMIN",
        identity_status="ACTIVE",
    )
    HrOrganizationVersion.objects.create(
        organization_id=org,
        tenant_id=tenant_id,
        name=name,
        org_type=org_type,
        validity_from=validity_from,
        validity_to=validity_to,
        version_no=1,
        status="EFFECTIVE",
    )
    return org
