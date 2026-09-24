from datetime import date
from uuid import uuid4

from django.db import connection

from hr_staff.models import HrAcademicProfileItem, HrPerson, HrStaffMaster
from hr_staff.services.academic_profile_service import revise_item
from hr10_development.constants import PlanLifecycleStatus, PlanType
from hr10_development.models import (
    HrCompetencyCatalog,
    HrDevelopmentNeed,
    HrDevelopmentPlan,
    HrLearningCompletion,
    HrLearningEnrollment,
    HrLearningOffering,
    HrProgramCompetencyOutcome,
    HrStaffCompetencyAssessment,
)
from hr10_development.services.competency_service import assess, apply_training_completion
from hr_self.services.case_service import create_case, hr_action, self_message
from hr_self.services.identity_service import SelfIdentityContext

assert connection.vendor == "mysql", connection.vendor
with connection.cursor() as cursor:
    cursor.execute("SELECT VERSION()")
    version = str(cursor.fetchone()[0])
assert version.startswith("8.4."), version

tenant_id = 1

person = HrPerson.objects.create(tenant_id=tenant_id, legal_name="MatureHR CI Teacher")
staff = HrStaffMaster.objects.create(
    tenant_id=tenant_id,
    person_id=person,
    staff_no="MATURE-HR-001",
)

first = revise_item(
    tenant_id=tenant_id,
    staff_id=staff.id,
    item_type="TEACHING_SUBJECT",
    name="数据库原理",
    level=3,
    is_primary=True,
)
second = revise_item(
    tenant_id=tenant_id,
    staff_id=staff.id,
    item_type="TEACHING_SUBJECT",
    name="Python程序设计",
    level=4,
    is_primary=True,
)
first.refresh_from_db()
assert first.is_current is False
current_subjects = HrAcademicProfileItem.objects.filter(
    tenant_id=tenant_id,
    staff_id=staff,
    item_type="TEACHING_SUBJECT",
    is_current=True,
)
assert current_subjects.filter(is_primary=True).count() == 1
assert current_subjects.get(is_primary=True).pk == second.pk

competency = HrCompetencyCatalog.objects.create(
    tenant_id=tenant_id,
    code="DIGITAL_TEACHING",
    name="数字化教学能力",
    max_level=5,
)
plan = HrDevelopmentPlan.objects.create(
    tenant_id=tenant_id,
    plan_no="MATURE-CI-2026",
    plan_type=PlanType.INDIVIDUAL,
    staff_master_uuid=staff.id,
    cycle_type="ANNUAL",
    start_date=date(2026, 1, 1),
    end_date=date(2026, 12, 31),
    lifecycle_status=PlanLifecycleStatus.ACTIVE,
    current_version_id=95001,
)
assessment, need = assess(
    tenant_id=tenant_id,
    staff_id=staff.id,
    competency_id=competency.id,
    current_level=2,
    target_level=4,
    verification_status="VERIFIED",
)
assert assessment.gap == 2
assert need is not None
assert HrDevelopmentNeed.objects.filter(pk=need.pk, source_type="SKILL_GAP").exists()

offering = HrLearningOffering.objects.create(
    tenant_id=tenant_id,
    program_version_id=97001,
    offering_no="MATURE-OFFERING-1",
    delivery_mode="OFFLINE",
)
enrollment = HrLearningEnrollment.objects.create(
    tenant_id=tenant_id,
    offering_id=offering.id,
    staff_master_uuid=staff.id,
    enrollment_status="COMPLETED",
)
HrProgramCompetencyOutcome.objects.create(
    tenant_id=tenant_id,
    program_version_id=97001,
    competency=competency,
    achieved_level=4,
)
completion = HrLearningCompletion.objects.create(
    tenant_id=tenant_id,
    enrollment_id=enrollment.id,
    program_version_id=97001,
    completion_status="PASS",
    verification_status="HR_VERIFIED",
)
updates = apply_training_completion(completion=completion)
assert updates and updates[0]["level"] == 4
current = HrStaffCompetencyAssessment.objects.get(
    tenant_id=tenant_id,
    staff_master_uuid=staff.id,
    competency=competency,
    is_current=True,
)
assert current.current_level == 4
assert current.verification_status == "VERIFIED"

context = SelfIdentityContext(
    tenant_id=tenant_id,
    user_id=88001,
    staff_id=staff.id,
    person_id=person.id,
    legacy_employee_id=None,
)
case = create_case(
    context=context,
    category="GRIEVANCE",
    subject="考核结果咨询",
    description="希望了解复核流程",
    priority=2,
)
case = hr_action(
    tenant_id=tenant_id,
    case_id=case.id,
    action="NEED_INFO",
    actor_user_id=99001,
    expected_version=1,
    message="请补充考核年度",
)
self_message(context=context, case_id=case.id, body="2025年度")
case.refresh_from_db()
assert case.status == "IN_PROGRESS"
case = hr_action(
    tenant_id=tenant_id,
    case_id=case.id,
    action="RESOLVE",
    actor_user_id=99001,
    expected_version=3,
    resolution_summary="已告知正式复核入口",
)
case = hr_action(
    tenant_id=tenant_id,
    case_id=case.id,
    action="CLOSE",
    actor_user_id=99001,
    expected_version=4,
)
assert case.status == "CLOSED"
assert case.messages.count() == 4

print("MATURE_HR_MYSQL84_SMOKE: PASS")
print("MYSQL_VERSION=" + version)
print("HR03_ACADEMIC_PROFILE=PASS")
print("HR10_COMPETENCY_TRAINING_CLOSURE=PASS")
print("HR17_SERVICE_CASE=PASS")
