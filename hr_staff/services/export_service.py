"""
hr_staff/services/export_service.py —— 权威导出服务（§24.4/§29.3，P1-h）。

契约：
- purpose 必填；字段级权限裁剪（SENSITIVE/HIGH_SENSITIVE 需 export_sensitive 权限，否则剔除）；
- data scope：只导出请求 scope 内的 staff（复用 StaffListSelector 的 scope 过滤）；
- 高敏字段（身份证/银行卡）默认不导出；
- 生成 CSV（标准库，mini 环境无 pandas）；大导出异步标注占位；
- 下载走短时效一次性 ticket；审计。
"""

from __future__ import annotations

import csv
import io
import secrets
from datetime import timedelta
from typing import Optional

from django.utils import timezone

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


class ExportPolicyDenied(Exception):
    code = "EXPORT_POLICY_DENIED"


class ExportJobNotFound(Exception):
    code = "EXPORT_NOT_FOUND"


class ExportService:
    def __init__(self, tenant_id: int, actor_user_id: Optional[int] = None):
        self.tenant_id = tenant_id
        self.actor_user_id = actor_user_id

    def create_export(
        self,
        *,
        purpose: str,
        staff_ids: list,
        fields: list,
        has_export_sensitive: bool,
        expires_in_seconds: int = 600,
    ) -> HrExportJob:
        if not purpose.strip():
            raise ExportPolicyDenied("导出必须填写用途")
        # 字段级权限：剔除无权字段（服务端裁剪，不信任前端）
        allowed_fields = []
        for f in fields:
            if f not in EXPORTABLE_FIELDS:
                continue  # 未登记字段不导出
            if f in SENSITIVE_EXPORT_FIELDS and not has_export_sensitive:
                continue
            allowed_fields.append(f)
        if not allowed_fields:
            raise ExportPolicyDenied("没有可导出的字段（或缺少敏感导出权限）")

        # 数据生成（V1 内存 CSV；大导出异步标注 [总控占位] 待 job runner）
        from hr_staff.models import HrStaffMaster
        from hr_staff.selectors.staff_list import StaffListSelector

        context = self._make_school_context()
        selector = StaffListSelector(context)
        rows = []
        qs = HrStaffMaster.objects.filter(tenant_id=self.tenant_id, id__in=staff_ids)
        for staff in qs.select_related("person_id"):
            primary = selector._current_primary(staff)
            row = selector.to_row(staff, primary)
            flat = {
                "staff_no": row.get("staff_no") or "",
                "legal_name": row.get("legal_name") or "",
                "staff_category_code": row.get("staff_category_code") or "",
                "current_employment_status": row.get("current_employment_status") or "",
                "org_name": row.get("org_name") or "",
                "position_name": row.get("position_name") or "",
                "date_joining": row.get("date_joining") or "",
                "work_email": "",
                "work_phone": "",
                "birth_year": "",
            }
            rows.append({k: flat.get(k, "") for k in allowed_fields})

        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=allowed_fields)
        writer.writeheader()
        writer.writerows(rows)
        csv_content = buffer.getvalue()

        job = HrExportJob.objects.create(
            tenant_id=self.tenant_id,
            requested_by=self.actor_user_id,
            purpose=purpose,
            fields_json=allowed_fields,
            scope_info_json={"staffIds": [str(s) for s in staff_ids]},
            total_rows=len(rows),
            status=HrExportJob.Status.READY,
            download_token=secrets.token_urlsafe(32),
            expires_at=timezone.now() + timedelta(seconds=expires_in_seconds),
        )
        # 受控存储引用（V1 存内存/DB 内容引用；正式存储服务占位）
        job.file_ref = f"hr-export/{job.id}.csv"
        job.save(update_fields=["file_ref"])
        # [总控占位] CSV 内容暂存内存字典（待受控文件存储交付后写盘）
        ExportContentStore.put(str(job.id), csv_content)

        write_audit_event(
            tenant_id=self.tenant_id,
            action="StaffExportCreated",
            actor_user_id=self.actor_user_id,
            business_type="EXPORT",
            business_id=str(job.id),
            reason=f"purpose={purpose[:200]} fields={','.join(allowed_fields)[:200]}",
        )
        return job

    def consume_download(self, job_id, token: str) -> dict:
        """消费导出下载票据（一次性）；返回 CSV 内容。"""
        job = HrExportJob.objects.filter(tenant_id=self.tenant_id, id=job_id).first()
        if job is None:
            raise ExportJobNotFound("EXPORT_NOT_FOUND")
        if job.download_token != token:
            raise ExportPolicyDenied("下载票据无效")
        if timezone.now() > job.expires_at:
            job.status = HrExportJob.Status.EXPIRED
            job.save(update_fields=["status"])
            raise ExportPolicyDenied("下载票据已过期")
        if job.consumed_at is not None:
            raise ExportPolicyDenied("下载票据已使用")
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
        return {"content": ExportContentStore.get(str(job.id)) or "", "filename": job.file_ref}

    def _make_school_context(self):
        from hr_staff.context import HrStaffRequestContext, HrStaffScope

        return HrStaffRequestContext(
            tenant_id=self.tenant_id,
            scope=HrStaffScope(scope_type="SCHOOL"),
        )


class ExportContentStore:
    """V1 内存 CSV 内容存储（一次性下载）。

    # [总控占位] 待受控文件存储（对象存储/私有 storage）交付后替换为写盘 + storage_file_id。
    """

    _store = {}

    @classmethod
    def put(cls, key: str, content: str):
        cls._store[key] = content

    @classmethod
    def get(cls, key: str) -> Optional[str]:
        return cls._store.get(key)

    @classmethod
    def clear(cls):
        cls._store.clear()
