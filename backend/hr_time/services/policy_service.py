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
from django.db import transaction
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

        # grace/rounding 基本合法性
        grace = version.grace_policy_json or {}
        for key in ("late_grace_minutes", "early_grace_minutes"):
            val = grace.get(key)
            if val is not None and (not isinstance(val, int) or val < 0):
                raise PublishGateError("INVALID_REQUEST", f"grace_policy_json.{key} 必须为非负整数")

        # 日历/班次引用（S3 交付后启用强校验）
        # calendar_version/ shift_version 引用字段随 S3 模型加入后再校验；
        # 当前阶段：引用为空不阻断（# [总控占位] S3 日历/班次模型交付后补强校验）

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
