"""
hr_time/services/policy_service.py

S2 政策版本服务：
- create_version / publish_version（Publish Gate，总册 §28）
- 发布时冻结 content_hash 并回写 policy_pack.current_version_id
- 规则变更只能新版本；PUBLISHED 后模型 save() 已 immutable（见 models/policy.py）
"""

from __future__ import annotations

from datetime import date

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone

from horilla.hr_event_service import emit_registered_event
from hr_time.enums import PolicyStatus
from hr_time.models.policy import HrTimePolicyPack, HrTimePolicyVersion


class PublishGateError(Exception):
    """发布前验收未通过。"""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


class PolicyService:
    @staticmethod
    def _run_publish_gate(version: HrTimePolicyVersion) -> None:
        """总册 §28 发布前验收（S2 阶段实现基础项；calendar/shift 等 S3 后补充）。"""
        if not version.effective_from:
            raise PublishGateError("INVALID_REQUEST", "版本缺少生效日")
        if version.effective_to and version.effective_to < version.effective_from:
            raise PublishGateError("INVALID_REQUEST", "失效日早于生效日")

        # recording profile 存在性（若版本声明使用）
        if version.recording_profile_id is not None:
            from hr_time.models.policy import HrTimeRecordingProfile

            if not HrTimeRecordingProfile.objects.filter(
                tenant_id=version.tenant_id, pk=version.recording_profile_id
            ).exists():
                raise PublishGateError("TIME_POLICY_NOT_FOUND", "记录方式不存在")
            profile = HrTimeRecordingProfile.objects.get(
                tenant_id=version.tenant_id, pk=version.recording_profile_id
            )
            if profile.effective_from > version.effective_from or (
                profile.effective_to
                and (
                    version.effective_to is None
                    or profile.effective_to < version.effective_to
                )
            ):
                raise PublishGateError(
                    "TIME_POLICY_NOT_FOUND", "记录方式有效期不能覆盖政策版本"
                )

        # grace/rounding 基本合法性
        grace = version.grace_policy_json or {}
        for key in ("late_grace_minutes", "early_grace_minutes"):
            val = grace.get(key)
            if val is not None and (not isinstance(val, int) or val < 0):
                raise PublishGateError("INVALID_REQUEST", f"grace_policy_json.{key} 必须为非负整数")

        def _reference_id(payload, *keys):
            if not isinstance(payload, dict):
                raise PublishGateError("INVALID_REQUEST", "日历/排班政策必须是 JSON 对象")
            return next((payload.get(key) for key in keys if payload.get(key)), None)

        calendar_id = _reference_id(
            version.work_calendar_policy,
            "calendarVersionId",
            "calendar_version_id",
        )
        if calendar_id is not None:
            from hr_time.models.calendar import HrWorkCalendarVersion

            calendar = HrWorkCalendarVersion.objects.filter(
                tenant_id=version.tenant_id,
                id=calendar_id,
                status="PUBLISHED",
            ).first()
            if calendar is None:
                raise PublishGateError(
                    "TIME_POLICY_NOT_FOUND", "工作日历版本不存在、未发布或跨学校"
                )
            if (
                version.effective_to
                and version.effective_to.year != version.effective_from.year
            ):
                raise PublishGateError(
                    "INVALID_REQUEST", "引用年度工作日历的政策版本不能跨自然年"
                )
            if calendar.year != version.effective_from.year:
                raise PublishGateError(
                    "INVALID_REQUEST", "工作日历年度与政策有效期不匹配"
                )

        shift_id = _reference_id(
            version.schedule_policy,
            "shiftVersionId",
            "shift_version_id",
        )
        if shift_id is not None:
            from hr_time.models.schedule import HrShiftVersion

            shift = HrShiftVersion.objects.filter(
                tenant_id=version.tenant_id,
                id=shift_id,
                published_at__isnull=False,
                effective_from__lte=version.effective_from,
            ).filter(
                models.Q(effective_to__isnull=True)
                | models.Q(effective_to__gte=version.effective_to or version.effective_from)
            ).first()
            if shift is None:
                raise PublishGateError(
                    "TIME_POLICY_NOT_FOUND", "班次版本不存在、未发布、跨学校或有效期不足"
                )

        scope = version.policy_pack.effective_scope or {"type": "TENANT_DEFAULT"}
        if not isinstance(scope, dict):
            raise PublishGateError("INVALID_REQUEST", "政策生效范围必须是 JSON 对象")
        scope_type = str(scope.get("type") or "TENANT_DEFAULT").upper()
        supported = {
            "TENANT_DEFAULT", "PERSON_EXCEPTION", "ASSIGNMENT", "ORG",
            "WORKER_CATEGORY", "EMPLOYMENT_TYPE",
        }
        if scope_type not in supported:
            raise PublishGateError("INVALID_REQUEST", f"不支持的政策生效范围: {scope_type}")
        required_keys = {
            "PERSON_EXCEPTION": ("person_ids", "personIds"),
            "ASSIGNMENT": ("assignment_ids", "assignmentIds"),
            "ORG": ("org_ids", "orgIds"),
            "WORKER_CATEGORY": ("categories",),
            "EMPLOYMENT_TYPE": ("employment_types", "employmentTypes"),
        }
        if scope_type in required_keys and not any(
            scope.get(key) for key in required_keys[scope_type]
        ):
            raise PublishGateError("INVALID_REQUEST", "政策生效范围缺少匹配值")

    @classmethod
    @transaction.atomic
    def publish_version(
        cls, version: HrTimePolicyVersion, *, actor_user=None
    ) -> HrTimePolicyVersion:
        """发布版本：冻结 content_hash + 回写 pack.current_version_id。"""
        if version.status == PolicyStatus.PUBLISHED:
            raise PublishGateError("VERSION_CONFLICT", "版本已是发布状态")
        if version.status == PolicyStatus.RETIRED:
            raise PublishGateError("VERSION_CONFLICT", "已退役版本不可发布")

        cls._run_publish_gate(version)

        version.status = PolicyStatus.PUBLISHED
        version.content_hash = version.compute_content_hash()
        version.published_at = timezone.now()
        if actor_user is not None:
            version.published_by_id = actor_user.id
            version.updated_by_id = actor_user.id
        version.save()

        pack = HrTimePolicyPack.objects.select_for_update().get(
            pk=version.policy_pack_id, tenant_id=version.tenant_id
        )
        pack.current_version_id = version.id
        pack.save(update_fields=["current_version_id", "updated_at"])
        emit_registered_event(
            tenant_id=version.tenant_id,
            event_name="hr.time.policy.published",
            correlation_id=f"hr11-policy:{version.id}:{version.version_no}",
            payload={
                "policyPackId": pack.id,
                "policyVersionId": version.id,
                "versionNo": version.version_no,
                "contentHash": version.content_hash,
                "effectiveFrom": version.effective_from.isoformat(),
            },
        )
        return version

    @staticmethod
    @transaction.atomic
    def retire_version(version: HrTimePolicyVersion, *, actor_user=None) -> HrTimePolicyVersion:
        """退役已发布版本（允许的唯一状态迁移）。"""
        if version.status != PolicyStatus.PUBLISHED:
            raise PublishGateError("VERSION_CONFLICT", "仅已发布版本可退役")
        version.status = PolicyStatus.RETIRED
        version.save(update_fields=["status", "updated_at"])
        return version
