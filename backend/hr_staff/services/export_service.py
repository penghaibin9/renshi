"""
hr_staff/services/export_service.py —— 权威导出服务（§24.4/§29.3，P1-h）。

契约：
- purpose 必填；字段级权限裁剪（SENSITIVE/HIGH_SENSITIVE 需 export_sensitive 权限，否则剔除）；
- data scope：只导出请求 scope 内的 staff，不能把调用者 scope 提升为 SCHOOL；
- 高敏字段（身份证/银行卡）默认不导出；
- 同步导出设置硬上限，防止 Web 请求无限吃内存；
- 内容写入 Django private storage，不依赖进程内内存；
- 下载 ticket 短时效、一次性、绑定申请人，并用行锁避免并发重复消费；
- 审计。
"""

from __future__ import annotations

import csv
import io
import secrets
from datetime import timedelta
from typing import Optional

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import transaction
from django.utils import timezone

from base.token_security import bearer_token_digest
from hr_staff.models import HrExportJob
from hr_staff.services.audit_service import write_audit_event

# 字段白名单（PUBLIC_HR/RESTRICTED_HR 可默认导出）
EXPORTABLE_FIELDS = frozenset(
    {
        "staff_no",
        "legal_name",
        "staff_category_code",
        "current_employment_status",
        "org_name",
        "position_name",
        "date_joining",
        "work_email",
        "work_phone",
    }
)
# 需 export_sensitive 权限的字段
SENSITIVE_EXPORT_FIELDS = frozenset({"work_phone", "birth_year"})
MAX_SYNC_EXPORT_STAFF = 5000


def _safe_csv_cell(value) -> str:
    """Return an Excel-safe text cell without changing the stored business value.

    CSV files are commonly opened directly in Excel/WPS.  Values beginning with
    formula sigils can otherwise be interpreted as formulas (including DDE or
    hyperlink payloads).  Prefixing an apostrophe makes the spreadsheet treat
    the value as text while preserving what the user sees.  Leading whitespace
    is inspected as well because spreadsheet parsers can normalize it before
    formula evaluation.
    """
    text = "" if value is None else str(value)
    significant = text.lstrip(" \t\r\n")
    if significant.startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r")):
        return "'" + text
    return text


class ExportPolicyDenied(Exception):
    code = "EXPORT_POLICY_DENIED"


class ExportJobNotFound(Exception):
    code = "EXPORT_NOT_FOUND"


class ExportContentUnavailable(Exception):
    code = "EXPORT_CONTENT_UNAVAILABLE"


class ExportService:
    def __init__(
        self,
        tenant_id: int,
        actor_user_id: Optional[int] = None,
        *,
        context=None,
    ):
        self.tenant_id = tenant_id
        self.actor_user_id = actor_user_id
        self.context = context

    def create_export(
        self,
        *,
        purpose: str,
        staff_ids: list,
        fields: list,
        has_export_sensitive: bool,
        expires_in_seconds: int = 600,
    ) -> HrExportJob:
        purpose = (purpose or "").strip()
        if not purpose:
            raise ExportPolicyDenied("导出必须填写用途")

        requested_ids = list(dict.fromkeys(str(value) for value in (staff_ids or []) if value))
        if len(requested_ids) > MAX_SYNC_EXPORT_STAFF:
            raise ExportPolicyDenied(
                f"单次同步导出最多 {MAX_SYNC_EXPORT_STAFF} 人，请缩小范围后重试"
            )

        # 字段级权限：剔除无权字段（服务端裁剪，不信任前端）
        allowed_fields = []
        for field in fields or []:
            if field not in EXPORTABLE_FIELDS:
                continue
            if field in SENSITIVE_EXPORT_FIELDS and not has_export_sensitive:
                continue
            if field not in allowed_fields:
                allowed_fields.append(field)
        if not allowed_fields:
            raise ExportPolicyDenied("没有可导出的字段（或缺少敏感导出权限）")

        from hr_staff.selectors.staff_list import StaffListSelector

        context = self.context or self._make_school_context()
        if context.tenant_id != self.tenant_id:
            raise ExportPolicyDenied("导出上下文与当前学校不一致")

        selector = StaffListSelector(context)
        scoped_qs = selector.apply_scope(selector.base_qs())
        scoped_qs = scoped_qs.filter(id__in=requested_ids)

        # 使用 selector 的批量路径，避免逐人员查询当前主岗和组织名称。
        staff_list = list(scoped_qs.order_by("staff_no"))
        primaries = selector._batch_current_primary(staff_list)
        future_flags = selector._batch_future_change(staff_list)
        org_names = selector._batch_org_names(primaries.values(), as_of=selector.as_of)

        rows = []
        for staff in staff_list:
            primary = primaries.get(staff.id)
            org_name = None
            if primary and primary.organization_id:
                org_name = (
                    org_names.get(primary.organization_id_id)
                    or primary.organization_id.stable_code
                )
            elif primary and primary.legacy_department_id:
                org_name = f"legacy:{primary.legacy_department_id}"
            row = selector.to_row(
                staff,
                primary,
                org_name=org_name,
                has_future_change=future_flags.get(staff.id, False),
            )
            flat = {
                "staff_no": row.get("staff_no") or "",
                "legal_name": row.get("legal_name") or "",
                "staff_category_code": row.get("staff_category_code") or "",
                "current_employment_status": row.get("current_employment_status") or "",
                "org_name": row.get("org_name") or "",
                "position_name": row.get("position_name") or "",
                "date_joining": row.get("date_joining") or "",
                # 联系方式仍由字段级 provider 接入后填充；禁止从 legacy 表绕读。
                "work_email": "",
                "work_phone": "",
                "birth_year": "",
            }
            rows.append(
                {key: _safe_csv_cell(flat.get(key, "")) for key in allowed_fields}
            )

        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=allowed_fields)
        writer.writeheader()
        writer.writerows(rows)
        csv_content = buffer.getvalue()

        raw_download_token = secrets.token_urlsafe(32)
        job = HrExportJob.objects.create(
            tenant_id=self.tenant_id,
            requested_by=self.actor_user_id,
            purpose=purpose,
            fields_json=allowed_fields,
            scope_info_json={
                "scope": context.scope.fingerprint,
                "staffIds": requested_ids,
            },
            total_rows=len(rows),
            status=HrExportJob.Status.PENDING,
            download_token=bearer_token_digest(
                raw_download_token, namespace="hr03-export-download"
            ),
            expires_at=timezone.now() + timedelta(seconds=expires_in_seconds),
        )
        try:
            file_ref = ExportContentStore.put(
                tenant_id=self.tenant_id,
                job_id=str(job.id),
                content=csv_content,
            )
        except Exception as exc:
            job.status = HrExportJob.Status.FAILED
            job.error = "受控文件存储写入失败"
            job.save(update_fields=["status", "error"])
            raise ExportContentUnavailable("导出文件暂时无法生成") from exc

        job.file_ref = file_ref
        job.status = HrExportJob.Status.READY
        job.save(update_fields=["file_ref", "status"])

        write_audit_event(
            tenant_id=self.tenant_id,
            action="StaffExportCreated",
            actor_user_id=self.actor_user_id,
            business_type="EXPORT",
            business_id=str(job.id),
            reason=f"purpose={purpose[:200]} fields={','.join(allowed_fields)[:200]}",
        )
        # The raw bearer token exists only in this response path; the database
        # retains its one-way digest so a database leak cannot redeem exports.
        job.issued_download_token = raw_download_token
        return job

    def consume_download(self, job_id, token: str) -> dict:
        """原子消费一次性下载票据；内容确认可读后才烧掉 ticket。"""
        content_unavailable = False
        content = None
        with transaction.atomic():
            job = (
                HrExportJob.objects.select_for_update()
                .filter(tenant_id=self.tenant_id, id=job_id)
                .first()
            )
            if job is None:
                raise ExportJobNotFound("EXPORT_NOT_FOUND")
            if job.requested_by is not None and job.requested_by != self.actor_user_id:
                raise ExportPolicyDenied("导出任务只允许申请人下载")
            supplied_digest = bearer_token_digest(
                token, namespace="hr03-export-download"
            )
            if not token or not secrets.compare_digest(
                job.download_token or "", supplied_digest
            ):
                raise ExportPolicyDenied("下载票据无效")
            if job.expires_at is None or timezone.now() > job.expires_at:
                job.status = HrExportJob.Status.EXPIRED
                job.save(update_fields=["status"])
                raise ExportPolicyDenied("下载票据已过期")
            if job.status != HrExportJob.Status.READY:
                raise ExportPolicyDenied("导出文件当前不可下载")
            if job.consumed_at is not None:
                raise ExportPolicyDenied("下载票据已使用")

            content = ExportContentStore.get(job.file_ref)
            if content is None:
                # Persist the terminal storage failure inside the row-lock
                # transaction, but raise only after this transaction commits.
                # Raising here would roll back FAILED -> READY and falsely leave
                # a missing file advertised as downloadable.
                job.status = HrExportJob.Status.FAILED
                job.error = "受控文件存储中找不到导出内容"
                job.save(update_fields=["status", "error"])
                content_unavailable = True
            else:
                job.consumed_at = timezone.now()
                job.save(update_fields=["consumed_at"])
                write_audit_event(
                    tenant_id=self.tenant_id,
                    action="StaffExportDownloaded",
                    actor_user_id=self.actor_user_id,
                    business_type="EXPORT",
                    business_id=str(job.id),
                    reason=job.purpose[:200],
                )

        if content_unavailable:
            raise ExportContentUnavailable("导出文件暂时不可用，请重新发起导出")

        # 一次性票据已原子消费。删除失败不影响本次已经读入内存的响应内容；
        # 后续生命周期清理仍可根据 job.file_ref 重试。
        try:
            ExportContentStore.delete(job.file_ref)
        except Exception:
            pass
        return {"content": content, "filename": job.file_ref}

    def _make_school_context(self):
        # 仅保留服务层兼容；HTTP 调用必须传入真实 request context。
        from hr_staff.context import HrStaffRequestContext, HrStaffScope

        return HrStaffRequestContext(
            tenant_id=self.tenant_id,
            scope=HrStaffScope(scope_type="SCHOOL"),
        )


class ExportContentStore:
    """基于 Django default_storage 的受控导出文件存储。

    默认部署写入受保护的 MEDIA storage；生产配置为私有对象存储时自动复用
    同一 storage backend。Nginx 不直接 alias /media，因此 file_ref 不是公开 URL。
    """

    _created_paths: set[str] = set()

    @classmethod
    def put(cls, *, tenant_id: int, job_id: str, content: str) -> str:
        path = f"hr-export/{tenant_id}/{job_id}.csv"
        if default_storage.exists(path):
            default_storage.delete(path)
        saved_path = default_storage.save(
            path,
            ContentFile(content.encode("utf-8-sig")),
        )
        cls._created_paths.add(saved_path)
        return saved_path

    @classmethod
    def get(cls, file_ref: str) -> Optional[str]:
        if not file_ref or not default_storage.exists(file_ref):
            return None
        with default_storage.open(file_ref, "rb") as handle:
            raw = handle.read()
        return raw.decode("utf-8-sig")

    @classmethod
    def delete(cls, file_ref: str) -> None:
        if file_ref and default_storage.exists(file_ref):
            default_storage.delete(file_ref)
        cls._created_paths.discard(file_ref)

    @classmethod
    def clear(cls):
        for path in list(cls._created_paths):
            try:
                cls.delete(path)
            except Exception:
                pass
        cls._created_paths.clear()
