"""Canonical HR03/HR09/HR16 providers for the HR01 headline metrics."""

from __future__ import annotations

import logging
from datetime import date

from django.db import DatabaseError
from django.db.models import Count, Max, Min, Q
from hr_control_center.providers.base import (
    DATA_BASIS_AUTHORITATIVE_EFFECTIVE_FACT,
    HrProviderError,
    ProviderResult,
    provider_ok,
)
from hr_control_center.services.metric_registry import get_registry

logger = logging.getLogger(__name__)


class CanonicalWorkforceMetricProvider:
    provider_key = "canonical_hr03_hr09_hr16"
    supported_metric_keys = {
        "active_headcount",
        "full_time_teacher",
        "double_teacher_valid",
        "new_join_ytd",
        "departure_ytd",
    }

    _STAFF_CATEGORY_LABELS = {
        "TEACHER": "教师",
        "ADMIN": "管理人员",
        "ENGINEERING_TECHNICAL": "工程技术人员",
        "EXPERIMENTAL": "实验技术人员",
        "LIBRARY_ARCHIVES": "图书档案人员",
        "LOGISTICS": "工勤技能人员",
        "OTHER": "其他人员",
    }
    _GENDER_LABELS = {
        "M": "男",
        "F": "女",
        "O": "其他",
        "U": "未说明",
    }

    def get_metric(self, metric_key, context) -> ProviderResult:
        definition = get_registry().get(metric_key)
        if definition is None or metric_key not in self.supported_metric_keys:
            return ProviderResult.unavailable(
                provider_key=self.provider_key,
                metric_key=metric_key,
                reason_code="METRIC_NOT_SUPPORTED",
                authority_mode=context.authority_mode,
            )
        if context.scope.scope_type != "SCHOOL" and metric_key in {
            "new_join_ytd",
            "departure_ytd",
        }:
            return ProviderResult.unavailable(
                provider_key=self.provider_key,
                metric_key=metric_key,
                reason_code="AUTHORITY_SCOPE_NOT_SUPPORTED",
                message="入职、离校期间指标当前仅支持学校范围，不会向院系范围泄露全校数字。",
                definition_version=definition.definition_version,
                authority_mode=context.authority_mode,
            )
        try:
            value, source_updated_at = getattr(self, f"_{metric_key}")(context)
        except DatabaseError as exc:
            raise HrProviderError(
                self.provider_key,
                metric_key,
                "AUTHORITY_QUERY_FAILED",
                tenant_id=context.tenant_id,
                scope_fingerprint=context.scope_fingerprint(),
            ) from exc
        if value is None:
            return ProviderResult.unavailable(
                provider_key=self.provider_key,
                metric_key=metric_key,
                reason_code="AUTHORITY_DATA_NOT_INITIALIZED",
                message="正式人事数据尚未完成迁移对账，暂不展示可能失真的数字。",
                definition_version=definition.definition_version,
                authority_mode=context.authority_mode,
            )
        data = {"value": value}
        if metric_key in {"new_join_ytd", "departure_ytd"}:
            data["period"] = {
                "from": date(context.as_of.year, 1, 1).isoformat(),
                "to": context.as_of.isoformat(),
            }
        return provider_ok(
            data,
            source=self.provider_key,
            source_updated_at=source_updated_at or context.request_snapshot_at,
            data_basis=DATA_BASIS_AUTHORITATIVE_EFFECTIVE_FACT,
            definition_version=definition.definition_version,
            authority_mode=context.authority_mode,
        )

    def get_workforce_sections(self, context) -> dict[str, ProviderResult]:
        """Return formal sections used by HR01's workforce summary."""
        sections = {}
        for section_key, metric_key in (
            ("fullTimeTeacher", "full_time_teacher"),
            ("doubleTeacher", "double_teacher_valid"),
        ):
            try:
                sections[section_key] = self.get_metric(metric_key, context)
            except Exception:
                logger.exception("canonical workforce metric failed metric=%s", metric_key)
                sections[section_key] = ProviderResult.unavailable(
                    provider_key=self.provider_key,
                    metric_key=metric_key,
                    reason_code="AUTHORITY_QUERY_FAILED",
                    message="该正式指标暂时无法计算。",
                    authority_mode=context.authority_mode,
                )
        for key, reader in (
            ("education", self._education_distribution),
            ("title", self._title_distribution),
        ):
            try:
                buckets, updated_at = reader(context)
                if buckets is None:
                    sections[key] = ProviderResult.unavailable(
                        provider_key=self.provider_key,
                        metric_key=f"workforce_{key}",
                        reason_code="AUTHORITY_DATA_NOT_INITIALIZED",
                        message="正式人事数据尚未完成迁移对账。",
                        authority_mode=context.authority_mode,
                    )
                else:
                    sections[key] = provider_ok(
                        {"buckets": buckets},
                        source=self.provider_key,
                        source_updated_at=updated_at or context.request_snapshot_at,
                        data_basis=DATA_BASIS_AUTHORITATIVE_EFFECTIVE_FACT,
                        authority_mode=context.authority_mode,
                    )
            except Exception:
                logger.exception("canonical workforce section failed section=%s", key)
                sections[key] = ProviderResult.unavailable(
                    provider_key=self.provider_key,
                    metric_key=f"workforce_{key}",
                    reason_code="AUTHORITY_QUERY_FAILED",
                    message="该正式结构数据暂时无法计算。",
                    authority_mode=context.authority_mode,
                )
        return sections

    def active_headcount(self, context) -> ProviderResult:
        """WorkforceProvider-compatible canonical headcount entry point."""
        return self.get_metric("active_headcount", context)

    def distribution_by_employee_type(self, context) -> ProviderResult:
        return self._distribution(
            context,
            metric_key="workforce_distribution_personnel_category",
            dimension="personnel_category",
            reader=self._staff_category_distribution,
        )

    def distribution_by_department(self, context) -> ProviderResult:
        return self._distribution(
            context,
            metric_key="workforce_distribution_department",
            dimension="department",
            reader=self._organization_distribution,
        )

    def distribution_by_hr02_org(self, context) -> ProviderResult:
        """Canonical assignments already reference HR02 organizations directly."""
        return self.distribution_by_department(context)

    def distribution_by_job_position(self, context) -> ProviderResult:
        return self._distribution(
            context,
            metric_key="workforce_distribution_job_position",
            dimension="job_position",
            reader=self._post_distribution,
        )

    def distribution_by_gender(self, context) -> ProviderResult:
        return self._distribution(
            context,
            metric_key="workforce_distribution_gender",
            dimension="gender",
            reader=self._gender_distribution,
        )

    def distribution_by_age_group(self, context) -> ProviderResult:
        return self._distribution(
            context,
            metric_key="workforce_distribution_age_group",
            dimension="age_group",
            reader=self._age_distribution,
        )

    def org_comparison(self, context) -> ProviderResult:
        metric_key = "workforce_org_comparison"
        unsupported = self._unsupported_scope(context, metric_key)
        if unsupported is not None:
            return unsupported
        try:
            relationships = self._active_relationships(context)
            if not self._authority_ready(context, relationships):
                return self._not_initialized(context, metric_key)
            staff_rows = list(
                self._active_staff(context, relationships).values(
                    "id",
                    "staff_category_code",
                    "person_id__gender_code",
                    "person_id__birth_date",
                )
            )
            assignments = self._primary_assignments(context, relationships)
            org_labels = self._organization_labels(
                context,
                {
                    row["organization_id"]
                    for row in assignments.values()
                    if row["organization_id"]
                },
            )
            rows = {}
            for staff in staff_rows:
                assignment = assignments.get(staff["id"])
                org_id = assignment["organization_id"] if assignment else None
                key = str(org_id) if org_id else "__none__"
                row = rows.setdefault(
                    key,
                    {
                        "departmentId": org_id,
                        "department": org_labels.get(org_id, "未设置"),
                        "headcount": 0,
                        "gender": {},
                        "employeeType": {},
                        "ageGroup": {},
                    },
                )
                row["headcount"] += 1
                gender = staff["person_id__gender_code"] or "U"
                self._increment_bucket(
                    row["gender"], gender, self._GENDER_LABELS.get(gender, "未说明")
                )
                category = staff["staff_category_code"] or "OTHER"
                self._increment_bucket(
                    row["employeeType"],
                    category,
                    self._STAFF_CATEGORY_LABELS.get(category, category),
                )
                age = self._age_on(staff["person_id__birth_date"], context.as_of)
                age_key, age_label = self._age_bucket(age)
                self._increment_bucket(row["ageGroup"], age_key, age_label)

            out_rows = []
            for row in rows.values():
                out_rows.append(
                    {
                        **{k: row[k] for k in ("departmentId", "department", "headcount")},
                        "gender": list(row["gender"].values()),
                        "employeeType": sorted(
                            row["employeeType"].values(),
                            key=lambda item: item["count"],
                            reverse=True,
                        ),
                        "ageGroup": list(row["ageGroup"].values()),
                    }
                )
            out_rows.sort(key=lambda item: item["headcount"], reverse=True)
            data = {"rows": out_rows, "total": len(staff_rows)}
            updated_at = self._source_updated_at(relationships)
        except Exception as exc:
            self._fail(context, metric_key, "ORG_COMPARISON_QUERY_FAILED", exc)
        return provider_ok(data, **self._base_kwargs(context, updated_at))

    def _distribution(self, context, *, metric_key, dimension, reader) -> ProviderResult:
        unsupported = self._unsupported_scope(context, metric_key)
        if unsupported is not None:
            return unsupported
        try:
            relationships = self._active_relationships(context)
            if not self._authority_ready(context, relationships):
                return self._not_initialized(context, metric_key)
            buckets, updated_at, extra = reader(context, relationships)
            data = {
                "dimension": dimension,
                "buckets": sorted(buckets, key=lambda item: item["count"], reverse=True),
                "total": sum(item["count"] for item in buckets),
                **extra,
            }
        except Exception as exc:
            self._fail(context, metric_key, "DISTRIBUTION_QUERY_FAILED", exc)
        return provider_ok(data, **self._base_kwargs(context, updated_at))

    def _unsupported_scope(self, context, metric_key):
        if context.scope.scope_type == "SCHOOL":
            return None
        if context.scope.scope_type in {"COLLEGE", "DEPARTMENT", "ASSIGNED"} and context.scope.org_id:
            return None
        return ProviderResult.unavailable(
            provider_key=self.provider_key,
            metric_key=metric_key,
            reason_code="AUTHORITY_SCOPE_NOT_SUPPORTED",
            message="当前数据范围缺少明确组织，系统已拒绝返回全校数据。",
            authority_mode=context.authority_mode,
        )

    def _not_initialized(self, context, metric_key):
        return ProviderResult.unavailable(
            provider_key=self.provider_key,
            metric_key=metric_key,
            reason_code="AUTHORITY_DATA_NOT_INITIALIZED",
            message="正式人事数据尚未完成迁移对账，暂不展示可能失真的结构数据。",
            authority_mode=context.authority_mode,
        )

    def _base_kwargs(self, context, updated_at=None):
        return {
            "computed_at": context.request_snapshot_at,
            "source_updated_at": updated_at or context.request_snapshot_at,
            "source": self.provider_key,
            "data_basis": DATA_BASIS_AUTHORITATIVE_EFFECTIVE_FACT,
            "authority_mode": context.authority_mode,
        }

    def _fail(self, context, metric_key, reason_code, exc):
        raise HrProviderError(
            self.provider_key,
            metric_key,
            reason_code,
            str(exc),
            tenant_id=context.tenant_id,
            scope_fingerprint=context.scope_fingerprint(),
        ) from exc

    @staticmethod
    def _active_staff(context, relationships):
        from hr_staff.models import HrStaffMaster

        return HrStaffMaster.objects.filter(
            tenant_id=context.tenant_id,
            id__in=relationships.values("staff_id"),
        ).distinct()

    @staticmethod
    def _source_updated_at(relationships):
        return relationships.aggregate(value=Max("updated_at"))["value"]

    def _staff_category_distribution(self, context, relationships):
        staff = self._active_staff(context, relationships)
        rows = staff.values("staff_category_code").annotate(count=Count("id"))
        buckets = [
            {
                "key": row["staff_category_code"] or "OTHER",
                "label": self._STAFF_CATEGORY_LABELS.get(
                    row["staff_category_code"] or "OTHER",
                    row["staff_category_code"] or "其他人员",
                ),
                "count": row["count"],
            }
            for row in rows
        ]
        updated = staff.aggregate(value=Max("updated_at"))["value"]
        return buckets, updated, {"interpretation": "HR03_STAFF_CATEGORY"}

    def _gender_distribution(self, context, relationships):
        staff = self._active_staff(context, relationships)
        rows = staff.values("person_id__gender_code").annotate(count=Count("id"))
        buckets = []
        for row in rows:
            key = row["person_id__gender_code"] or "U"
            buckets.append(
                {
                    "key": key,
                    "label": self._GENDER_LABELS.get(key, "未说明"),
                    "count": row["count"],
                }
            )
        updated = staff.aggregate(value=Max("person_id__updated_at"))["value"]
        return buckets, updated, {}

    def _age_distribution(self, context, relationships):
        from hr_control_center.providers.workforce import AGE_GROUPS, AGE_GROUP_LABELS

        staff = self._active_staff(context, relationships)
        counts = {key: 0 for key, _label, _limits in AGE_GROUPS}
        unknown = 0
        for birth_date in staff.values_list("person_id__birth_date", flat=True):
            key, _label = self._age_bucket(self._age_on(birth_date, context.as_of))
            if key == "__unknown__":
                unknown += 1
            else:
                counts[key] += 1
        buckets = [
            {"key": key, "label": AGE_GROUP_LABELS[key], "count": value}
            for key, value in counts.items()
            if value
        ]
        if unknown:
            buckets.append(
                {"key": "__unknown__", "label": "未设置/日期异常", "count": unknown}
            )
        updated = staff.aggregate(value=Max("person_id__updated_at"))["value"]
        return buckets, updated, {}

    def _organization_distribution(self, context, relationships):
        assignments = self._primary_assignments(context, relationships)
        labels = self._organization_labels(
            context,
            {
                row["organization_id"]
                for row in assignments.values()
                if row["organization_id"]
            },
        )
        counts = {}
        for staff_id in self._active_staff(context, relationships).values_list(
            "id", flat=True
        ):
            row = assignments.get(staff_id)
            org_id = row["organization_id"] if row else None
            key = str(org_id) if org_id else "__none__"
            entry = counts.setdefault(
                key,
                {"key": key, "label": labels.get(org_id, "未设置"), "count": 0},
            )
            entry["count"] += 1
        return (
            list(counts.values()),
            self._assignment_updated_at(assignments),
            {"interpretation": "HR02_AUTHORITY_ORG"},
        )

    def _post_distribution(self, context, relationships):
        assignments = self._primary_assignments(context, relationships)
        counts = {}
        for staff_id in self._active_staff(context, relationships).values_list(
            "id", flat=True
        ):
            row = assignments.get(staff_id)
            post_id = row["post_catalog_id"] if row else None
            key = str(post_id) if post_id else "__none__"
            label = (
                row["post_catalog_id__name"]
                if row and row["post_catalog_id__name"]
                else "未设置"
            )
            entry = counts.setdefault(key, {"key": key, "label": label, "count": 0})
            entry["count"] += 1
        return (
            list(counts.values()),
            self._assignment_updated_at(assignments),
            {"interpretation": "HR02_POST_CATALOG"},
        )

    @staticmethod
    def _primary_assignments(context, relationships):
        from hr_staff.constants import AssignmentStatus, AssignmentType
        from hr_staff.models import HrStaffAssignment

        qs = (
            HrStaffAssignment.objects.filter(
                tenant_id=context.tenant_id,
                employment_relationship_id__in=relationships.values("id"),
                assignment_type=AssignmentType.PRIMARY,
                status__in=(AssignmentStatus.ACTIVE, AssignmentStatus.ENDING_SOON),
                effective_from__lte=context.as_of,
            )
            .filter(Q(effective_to__isnull=True) | Q(effective_to__gt=context.as_of))
            .values(
                "employment_relationship_id__staff_id",
                "organization_id",
                "post_catalog_id",
                "post_catalog_id__name",
                "effective_from",
                "updated_at",
            )
            .order_by(
                "employment_relationship_id__staff_id",
                "-effective_from",
                "-updated_at",
            )
        )
        selected = {}
        for row in qs:
            selected.setdefault(row["employment_relationship_id__staff_id"], row)
        return selected

    @staticmethod
    def _organization_labels(context, organization_ids):
        if not organization_ids:
            return {}
        from hr_structure.models import HrOrganizationVersion

        versions = (
            HrOrganizationVersion.objects.filter(
                tenant_id=context.tenant_id,
                organization_id__in=organization_ids,
                status__in=("APPROVED", "EFFECTIVE", "SUPERSEDED"),
                validity_from__lte=context.as_of,
            )
            .filter(Q(validity_to__isnull=True) | Q(validity_to__gt=context.as_of))
            .values("organization_id", "name", "validity_from")
            .order_by("organization_id", "-validity_from")
        )
        labels = {}
        for row in versions:
            labels.setdefault(row["organization_id"], row["name"])
        return labels

    @staticmethod
    def _assignment_updated_at(assignments):
        return max(
            (row["updated_at"] for row in assignments.values() if row.get("updated_at")),
            default=None,
        )

    @staticmethod
    def _increment_bucket(container, key, label):
        bucket = container.setdefault(key, {"key": key, "label": label, "count": 0})
        bucket["count"] += 1

    @staticmethod
    def _age_on(birth_date, as_of):
        if not birth_date:
            return None
        return as_of.year - birth_date.year - (
            1 if (as_of.month, as_of.day) < (birth_date.month, birth_date.day) else 0
        )

    @staticmethod
    def _age_bucket(age):
        from hr_control_center.providers.workforce import AGE_GROUPS, AGE_GROUP_LABELS

        if age is None or age < 0:
            return "__unknown__", "未设置/日期异常"
        for key, _label, (low, high) in AGE_GROUPS:
            if (low is None or age >= low) and (high is None or age <= high):
                return key, AGE_GROUP_LABELS[key]
        return "__unknown__", "未设置/日期异常"

    @classmethod
    def _active_relationships(cls, context):
        from hr_staff.constants import RelationshipStatus
        from hr_staff.models import HrEmploymentRelationship

        as_of = context.as_of
        relationships = (
            HrEmploymentRelationship.objects.filter(
                tenant_id=context.tenant_id,
                status=RelationshipStatus.ACTIVE,
                effective_from__lte=as_of,
            )
            .filter(Q(effective_to__isnull=True) | Q(effective_to__gt=as_of))
        )
        if context.scope.scope_type == "SCHOOL":
            return relationships
        if context.scope.scope_type not in {"COLLEGE", "DEPARTMENT", "ASSIGNED"}:
            return relationships.none()
        if not context.scope.org_id:
            return relationships.none()

        from hr_staff.constants import AssignmentStatus, AssignmentType
        from hr_staff.models import HrStaffAssignment
        from hr_structure.selectors.effective import build_tree_as_of

        try:
            nodes = build_tree_as_of(
                context.tenant_id,
                context.scope.org_id,
                as_of,
                depth_limit=6,
            )
            organization_ids = {node["id"] for node in nodes} | {
                context.scope.org_id
            }
        except Exception:
            # The explicitly authorized root remains the narrowest safe fallback.
            organization_ids = {context.scope.org_id}

        scoped_staff_ids = (
            HrStaffAssignment.objects.filter(
                tenant_id=context.tenant_id,
                assignment_type=AssignmentType.PRIMARY,
                status__in=(AssignmentStatus.ACTIVE, AssignmentStatus.ENDING_SOON),
                organization_id__in=organization_ids,
                effective_from__lte=as_of,
            )
            .filter(Q(effective_to__isnull=True) | Q(effective_to__gt=as_of))
            .values("employment_relationship_id__staff_id")
        )
        return relationships.filter(staff_id__in=scoped_staff_ids)

    @staticmethod
    def _legacy_active_count(context) -> int:
        from employee.models import EmployeeWorkInformation

        return (
            EmployeeWorkInformation.objects.filter(
                company_id_id=context.tenant_id,
                employee_id__is_active=True,
            )
            .values("employee_id")
            .distinct()
            .count()
        )

    def _authority_ready(self, context, active_relationships) -> bool:
        if context.authority_mode == "AUTHORITY_ONLY":
            return True
        if context.scope.scope_type != "SCHOOL":
            return False
        return (
            active_relationships.values("staff_id").distinct().count()
            == self._legacy_active_count(context)
        )

    def _active_headcount(self, context):
        relationships = self._active_relationships(context)
        if not self._authority_ready(context, relationships):
            return None, None
        summary = relationships.aggregate(source_updated_at=Max("updated_at"))
        return relationships.values("staff_id").distinct().count(), summary["source_updated_at"]

    def _full_time_teacher(self, context):
        from hr_staff.constants import EmploymentType, StaffCategoryCode

        relationships = self._active_relationships(context)
        if not self._authority_ready(context, relationships):
            return None, None
        teachers = relationships.filter(
            employment_type=EmploymentType.FULL_TIME,
            staff_id__staff_category_code=StaffCategoryCode.TEACHER,
        )
        summary = teachers.aggregate(source_updated_at=Max("updated_at"))
        return teachers.values("staff_id").distinct().count(), summary["source_updated_at"]

    def _double_teacher_valid(self, context):
        from hr_qualification.constants import RecognitionStatus
        from hr_qualification.models import HrDoubleTeacherRecognition

        relationships = self._active_relationships(context)
        if not self._authority_ready(context, relationships):
            return None, None
        staff_ids = relationships.values("staff_id")
        recognitions = (
            HrDoubleTeacherRecognition.objects.filter(
                tenant_id=context.tenant_id,
                staff_master_id__in=staff_ids,
                status__in=(
                    RecognitionStatus.ACTIVE,
                    RecognitionStatus.REVIEW_DUE,
                    RecognitionStatus.UNDER_REVIEW,
                ),
                effective_from__lte=context.as_of,
            )
            .filter(Q(effective_to__isnull=True) | Q(effective_to__gte=context.as_of))
        )
        summary = recognitions.aggregate(source_updated_at=Max("updated_at"))
        return recognitions.values("person_id").distinct().count(), summary["source_updated_at"]

    def _education_distribution(self, context):
        from hr_staff.constants import VerificationStatus
        from hr_staff.models import HrEducationExperience

        relationships = self._active_relationships(context)
        if not self._authority_ready(context, relationships):
            return None, None
        rows = (
            HrEducationExperience.objects.filter(
                tenant_id=context.tenant_id,
                staff_id__in=relationships.values("staff_id"),
                is_highest_education=True,
                verification_status=VerificationStatus.VERIFIED,
            )
            .values("education_level")
            .annotate(count=Count("staff_id", distinct=True))
            .order_by("education_level")
        )
        updated_at = HrEducationExperience.objects.filter(
            tenant_id=context.tenant_id,
            staff_id__in=relationships.values("staff_id"),
            is_highest_education=True,
            verification_status=VerificationStatus.VERIFIED,
        ).aggregate(value=Max("updated_at"))["value"]
        return [
            {"label": row["education_level"] or "未分类", "count": row["count"]}
            for row in rows
        ], updated_at

    def _title_distribution(self, context):
        from hr_title.models import ProfessionalTitleResult

        relationships = self._active_relationships(context)
        if not self._authority_ready(context, relationships):
            return None, None
        active_person_ids = relationships.values("staff_id__person_id")
        all_formal = ProfessionalTitleResult.objects.filter(
            tenant_id=context.tenant_id,
            person_id__in=active_person_ids,
            status__in=(
                ProfessionalTitleResult.Status.EFFECTIVE,
                ProfessionalTitleResult.Status.REVISED,
                ProfessionalTitleResult.Status.REVOKED,
            ),
        )
        superseded_ids = all_formal.exclude(supersedes_result_id__isnull=True).values(
            "supersedes_result_id"
        )
        current = (
            all_formal.filter(
                status__in=(
                    ProfessionalTitleResult.Status.EFFECTIVE,
                    ProfessionalTitleResult.Status.REVISED,
                ),
                effective_from__lte=context.as_of,
            )
            .filter(Q(effective_to__isnull=True) | Q(effective_to__gt=context.as_of))
            .exclude(id__in=superseded_ids)
        )
        rows = (
            current.values("title_level_code")
            .annotate(count=Count("person_id", distinct=True))
            .order_by("title_level_code")
        )
        updated_at = current.aggregate(value=Max("updated_at"))["value"]
        return [
            {"label": row["title_level_code"] or "未分级", "count": row["count"]}
            for row in rows
        ], updated_at

    @staticmethod
    def _new_join_ytd(context):
        from hr_staff.constants import RelationshipStatus
        from hr_staff.models import HrEmploymentRelationship

        year_start = date(context.as_of.year, 1, 1)
        first_relationships = (
            HrEmploymentRelationship.objects.filter(
                tenant_id=context.tenant_id,
                status__in=(RelationshipStatus.ACTIVE, RelationshipStatus.ENDED),
                effective_from__lte=context.as_of,
            )
            .values("staff_id")
            .annotate(first_effective_from=Min("effective_from"))
            .filter(first_effective_from__gte=year_start)
        )
        source_updated_at = HrEmploymentRelationship.objects.filter(
            tenant_id=context.tenant_id,
            staff_id__in=first_relationships.values("staff_id"),
        ).aggregate(value=Max("updated_at"))["value"]
        return first_relationships.count(), source_updated_at

    @staticmethod
    def _departure_ytd(context):
        from hr_exit.models import ExitFact

        year_start = date(context.as_of.year, 1, 1)
        all_formal = ExitFact.objects.filter(
            tenant_id=context.tenant_id,
            status__in=(
                ExitFact.Status.EFFECTIVE,
                ExitFact.Status.REVISED,
                ExitFact.Status.REVOKED,
            ),
        )
        if context.authority_mode != "AUTHORITY_ONLY" and not all_formal.exists():
            # A registered HR16 app/table is not proof that this tenant's
            # historical departures were reconciled.  Before authority
            # cutover, an empty formal ledger must remain unavailable instead
            # of being rendered as a misleading zero.
            return None, None
        superseded_ids = all_formal.exclude(supersedes_fact_id__isnull=True).values(
            "supersedes_fact_id"
        )
        current_facts = all_formal.filter(
            status__in=(ExitFact.Status.EFFECTIVE, ExitFact.Status.REVISED),
            employment_end_date__gte=year_start,
            employment_end_date__lte=context.as_of,
        ).exclude(id__in=superseded_ids)
        summary = current_facts.aggregate(source_updated_at=Max("updated_at"))
        return current_facts.values("person_id").distinct().count(), summary["source_updated_at"]
