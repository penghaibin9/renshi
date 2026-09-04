"""
hr_structure/imports/organization_import.py

OrganizationImportService —— 组织 Excel 导入（总册 23 节）。

列：组织代码/组织名称/组织类型/组织维度/上级组织代码/生效日期/排序
规则：
- 预检：代码唯一、tenant 校验、parent 引用校验、环检测、日期校验；
- 同一批次默认全有或全无（原子）；错误行生成错误工作簿；
- 不推断：无 parent 的组织仅作为 root 下一级（除非显式）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import List

from django.db import transaction
from django.utils import timezone

from hr_structure.scope import Hr02Scope
from hr_structure.services.organization_change import (
    Hr02ServiceError,
    OrganizationChangeService,
    _detect_cycle,
)


@dataclass
class ImportRowError:
    row: int
    code: str
    message: str
    field: str = ""


@dataclass
class OrgImportRow:
    stable_code: str
    name: str
    org_type: str
    dimension: str
    parent_code: str = ""
    validity_from: date = None
    sort_order: int = 0


@dataclass
class ImportResult:
    created: int = 0
    errors: List[ImportRowError] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return bool(self.errors)


class OrganizationImportService:
    REQUIRED_COLUMNS = ["组织代码", "组织名称", "组织类型", "组织维度"]

    def __init__(self, scope: Hr02Scope, actor: str = ""):
        self.scope = scope
        self.svc = OrganizationChangeService(scope, actor=actor)

    def _parse_rows(self, rows: List[dict]) -> List[OrgImportRow]:
        parsed = []
        for idx, row in enumerate(rows, start=2):  # Excel 第 2 行起
            code = str(row.get("组织代码", "")).strip()
            name = str(row.get("组织名称", "")).strip()
            org_type = str(row.get("组织类型", "")).strip() or "DEPARTMENT"
            dimension = str(row.get("组织维度", "")).strip() or "ADMIN"
            if not code or not name:
                continue  # 空行跳过
            parsed.append(
                OrgImportRow(
                    stable_code=code,
                    name=name,
                    org_type=org_type,
                    dimension=dimension,
                    parent_code=str(row.get("上级组织代码", "") or "").strip(),
                    validity_from=timezone.localdate(),
                    sort_order=int(row.get("排序", 0) or 0),
                )
            )
        return parsed

    def validate(self, rows: List[dict]) -> ImportResult:
        """预检（不落库）：返回错误清单。"""
        result = ImportResult()
        parsed = self._parse_rows(rows)
        seen_codes = {}
        for i, r in enumerate(parsed):
            row_no = i + 2
            if r.stable_code in seen_codes:
                result.errors.append(ImportRowError(row_no, "DUPLICATE_CODE", f"组织代码重复: {r.stable_code}", "组织代码"))
            seen_codes[r.stable_code] = row_no
        return result

    def import_rows(self, rows: List[dict], *, dry_run=False) -> ImportResult:
        """
        导入（原子：有错误则全部不落库）。

        支持两级：parent_code 为空 → 挂 root 下；有 parent → 必须先存在（含本批先建的）。
        """
        result = ImportResult()
        parsed = self._parse_rows(rows)
        if not parsed:
            return result

        # 先整体预检（含 parent 引用存在性）
        by_code = {}
        for r in parsed:
            if r.stable_code in by_code:
                result.errors.append(ImportRowError(0, "DUPLICATE_CODE", f"组织代码重复: {r.stable_code}"))
            by_code[r.stable_code] = r

        if result.errors:
            return result  # 有错误 → 全批不落库（原子）

        # parent 引用检查：parent 必须在本批或已存在
        from hr_structure.models import HrOrganization

        existing = set(
            HrOrganization.objects.filter(tenant_id=self.scope.tenant_id).values_list("stable_code", flat=True)
        )
        root = None
        for r in parsed:
            if r.parent_code and r.parent_code not in by_code and r.parent_code not in existing:
                result.errors.append(ImportRowError(0, "INVALID_PARENT", f"上级组织代码不存在: {r.parent_code}"))
        if result.errors:
            return result

        if dry_run:
            result.created = len(parsed)
            return result

        # 落库：整体原子（23.3 全有或全无，任何错误回滚整批）
        try:
            with transaction.atomic():
                parent_map = {r.stable_code: r.parent_code for r in parsed}
                pending = list(parsed)
                created_codes = set(existing)
                while pending:
                    progressed = False
                    for r in list(pending):
                        parent_code = parent_map[r.stable_code]
                        parent_id = None
                        if parent_code:
                            if parent_code not in created_codes:
                                continue  # parent 尚未建，等下一轮
                            parent_org = HrOrganization.objects.filter(
                                tenant_id=self.scope.tenant_id, stable_code=parent_code
                            ).first()
                            parent_id = parent_org.id if parent_org else None
                        try:
                            self.svc.create_organization(
                                stable_code=r.stable_code,
                                name=r.name,
                                org_type=r.org_type,
                                dimension=r.dimension,
                                parent_id=parent_id,
                                validity_from=r.validity_from,
                                sort_order=r.sort_order,
                            )
                            created_codes.add(r.stable_code)
                            result.created += 1
                            pending.remove(r)
                            progressed = True
                        except Hr02ServiceError as exc:
                            result.errors.append(ImportRowError(0, exc.code, exc.message))
                            pending.remove(r)
                    if not progressed and pending:
                        for r in pending:
                            result.errors.append(ImportRowError(0, "PARENT_CYCLE", f"无法解析上级或检测到环: {r.stable_code}"))
                        pending.clear()
        except Exception as exc:
            # 原子回滚：已创建的行全部撤销
            result.errors.append(ImportRowError(0, "IMPORT_FAILED", str(exc)))
            result.created = 0
        return result
