"""
hr10_development/providers/person_provider.py

HR03 Person/Staff Provider 实现。

S9 阶段：直接引用 HR03 模型（内部 Provider，非 HTTP）。
生产阶段：可切换为 HTTP/gRPC 远程调用。
"""

from hr10_development.providers.base import PersonProvider, ProviderResult, ProviderStatus


class Hr03PersonProvider(PersonProvider):
    """HR03 Person/Staff Provider — 内部 ORM 直连实现。"""

    def get_person(self, person_id: str, tenant_id: int) -> ProviderResult:
        try:
            from hr_staff.models.person import HrPerson
            p = HrPerson.objects.get(id=person_id, tenant_id=tenant_id)
            return ProviderResult(
                status=ProviderStatus.OK,
                data={"id": str(p.id), "legalName": p.legal_name, "genderCode": p.gender_code, "status": p.status},
            )
        except Exception as e:
            return ProviderResult(status=ProviderStatus.ERROR, error_message=str(e))

    def get_staff_master(self, staff_master_id: str, tenant_id: int) -> ProviderResult:
        try:
            from hr_staff.models.staff import HrStaffMaster
            s = HrStaffMaster.objects.get(id=staff_master_id, tenant_id=tenant_id)
            return ProviderResult(
                status=ProviderStatus.OK,
                data={"id": str(s.id), "staffNo": s.staff_no, "staffCategoryCode": s.staff_category_code},
            )
        except Exception as e:
            return ProviderResult(status=ProviderStatus.ERROR, error_message=str(e))

    def get_employment_relationship(self, relationship_id: str, tenant_id: int) -> ProviderResult:
        from hr_staff.models.employment import HrEmploymentRelationship
        try:
            r = HrEmploymentRelationship.objects.get(id=relationship_id, tenant_id=tenant_id)
            return ProviderResult(status=ProviderStatus.OK, data={"id": str(r.id), "status": r.status})
        except Exception as e:
            return ProviderResult(status=ProviderStatus.ERROR, error_message=str(e))

    def get_assignment(self, assignment_id: str, tenant_id: int) -> ProviderResult:
        from hr_staff.models.assignment import HrStaffAssignment
        try:
            a = HrStaffAssignment.objects.get(id=assignment_id, tenant_id=tenant_id)
            return ProviderResult(status=ProviderStatus.OK, data={"id": str(a.id), "fte": str(a.fte)})
        except Exception as e:
            return ProviderResult(status=ProviderStatus.ERROR, error_message=str(e))

    def get_education_history(self, staff_master_id: str, tenant_id: int, as_of=None) -> ProviderResult:
        from hr_staff.models.education import HrEducationExperience
        qs = HrEducationExperience.objects.filter(staff_master_id=staff_master_id, tenant_id=tenant_id)
        data = [{"id": str(e.id), "school": e.school, "educationLevel": e.education_level, "major": e.major} for e in qs[:50]]
        return ProviderResult(status=ProviderStatus.OK, data=data)
