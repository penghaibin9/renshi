"""Explicit HR03 correction-field validators and Authority applicators."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Callable

from django.core.validators import validate_email

from hr_staff.constants import StaffCategoryCode


class CorrectionFieldApplicationError(Exception):
    """A registered field cannot safely be applied with the supplied evidence."""

    code = "CORRECTION_FIELD_APPLICATION_DENIED"


Validator = Callable[[object, object], object]
Applicator = Callable[[object, object, object, object], None]


@dataclass(frozen=True)
class CorrectionFieldHandler:
    field_code: str
    validator: Validator
    applicator: Applicator

    def apply(self, service, case, item) -> None:
        value = self.validator(item.new_value_masked, item)
        self.applicator(service, case, item, value)


def _required_text(value, item):
    value = str(value or "").strip()
    if not value:
        raise CorrectionFieldApplicationError(f"{item.field_code}: 新值不能为空")
    return value


def _optional_text(value, _item):
    return str(value or "").strip()


def _email(value, item):
    value = _required_text(value, item)
    try:
        validate_email(value)
    except Exception as exc:
        raise CorrectionFieldApplicationError(f"{item.field_code}: 邮箱格式无效") from exc
    return value


def _gender(value, item):
    value = _required_text(value, item).upper()
    if value not in {"M", "F", "O", "U"}:
        raise CorrectionFieldApplicationError(f"{item.field_code}: 性别代码无效")
    return value


def _birth_date(value, item):
    try:
        parsed = date.fromisoformat(str(value or ""))
    except ValueError as exc:
        raise CorrectionFieldApplicationError(
            f"{item.field_code}: 日期必须为 YYYY-MM-DD"
        ) from exc
    if parsed > date.today():
        raise CorrectionFieldApplicationError(f"{item.field_code}: 出生日期不能晚于今天")
    return parsed


def _staff_category(value, item):
    value = _required_text(value, item).upper()
    if value not in StaffCategoryCode.values:
        raise CorrectionFieldApplicationError(f"{item.field_code}: 人员类别无效")
    return value


def _apply_person_attribute(attribute: str):
    def apply(_service, case, _item, value):
        person = case.staff_id.person_id
        setattr(person, attribute, value)
        person.version += 1
        person.save(update_fields=[attribute, "version", "updated_at"])

    return apply


def _apply_contact(kind: str):
    def apply(service, case, _item, value):
        service._upsert_contact(case.staff_id, kind, value)

    return apply


def _apply_staff_no(_service, case, item, value):
    from hr_staff.models import HrStaffMaster

    if HrStaffMaster.objects.filter(
        tenant_id=case.tenant_id, staff_no=value
    ).exclude(id=case.staff_id_id).exists():
        raise CorrectionFieldApplicationError(f"{item.field_code}: 工号已存在")
    staff = case.staff_id
    staff.staff_no = value
    staff.version += 1
    staff.save(update_fields=["staff_no", "version", "updated_at"])


def _apply_staff_category(_service, case, _item, value):
    staff = case.staff_id
    staff.staff_category_code = value
    staff.version += 1
    staff.save(update_fields=["staff_category_code", "version", "updated_at"])


def _blocked(reason: str):
    def validate(_value, item):
        raise CorrectionFieldApplicationError(f"{item.field_code}: {reason}")

    return validate


def _never_apply(_service, _case, item, _value):  # pragma: no cover - validator blocks
    raise CorrectionFieldApplicationError(f"{item.field_code}: 字段应用被拒绝")


FIELD_CORRECTION_HANDLERS = {
    "person.legal_name": CorrectionFieldHandler(
        "person.legal_name", _required_text, _apply_person_attribute("legal_name")
    ),
    "person.preferred_name": CorrectionFieldHandler(
        "person.preferred_name", _optional_text, _apply_person_attribute("preferred_name")
    ),
    "person.gender_code": CorrectionFieldHandler(
        "person.gender_code", _gender, _apply_person_attribute("gender_code")
    ),
    "person.birth_date": CorrectionFieldHandler(
        "person.birth_date", _birth_date, _apply_person_attribute("birth_date")
    ),
    "contact.mobile": CorrectionFieldHandler(
        "contact.mobile", _required_text, _apply_contact("PERSONAL_MOBILE")
    ),
    "contact.personal_email": CorrectionFieldHandler(
        "contact.personal_email", _email, _apply_contact("PERSONAL_EMAIL")
    ),
    "contact.work_email": CorrectionFieldHandler(
        "contact.work_email", _email, _apply_contact("WORK_EMAIL")
    ),
    "contact.work_phone": CorrectionFieldHandler(
        "contact.work_phone", _required_text, _apply_contact("WORK_MOBILE")
    ),
    "staff.staff_no": CorrectionFieldHandler(
        "staff.staff_no", _required_text, _apply_staff_no
    ),
    "staff.staff_category_code": CorrectionFieldHandler(
        "staff.staff_category_code", _staff_category, _apply_staff_category
    ),
    "identity.document_number": CorrectionFieldHandler(
        "identity.document_number",
        _blocked("必须使用受控密文引用和专用双人复核流程，禁止从掩码值写入"),
        _never_apply,
    ),
    "employment.relationship_type": CorrectionFieldHandler(
        "employment.relationship_type", _blocked("仅能由正式业务流程变更"), _never_apply
    ),
    "employment.effective_from": CorrectionFieldHandler(
        "employment.effective_from", _blocked("仅能由正式业务流程变更"), _never_apply
    ),
    "assignment.organization": CorrectionFieldHandler(
        "assignment.organization", _blocked("仅能由正式业务流程变更"), _never_apply
    ),
    "assignment.position": CorrectionFieldHandler(
        "assignment.position", _blocked("仅能由正式业务流程变更"), _never_apply
    ),
    "assignment.assignment_type": CorrectionFieldHandler(
        "assignment.assignment_type", _blocked("仅能由正式业务流程变更"), _never_apply
    ),
    "staff.employment_status": CorrectionFieldHandler(
        "staff.employment_status", _blocked("仅能由正式业务流程变更"), _never_apply
    ),
    "background.education": CorrectionFieldHandler(
        "background.education", _blocked("必须通过学历经历版本服务办理"), _never_apply
    ),
    "background.credential": CorrectionFieldHandler(
        "background.credential", _blocked("必须通过资质凭证版本服务办理"), _never_apply
    ),
}


def get_correction_field_handler(field_code: str) -> CorrectionFieldHandler:
    try:
        return FIELD_CORRECTION_HANDLERS[field_code]
    except KeyError as exc:
        raise CorrectionFieldApplicationError(f"未登记更正应用器: {field_code}") from exc
