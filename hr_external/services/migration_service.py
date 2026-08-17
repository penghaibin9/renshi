"""
hr_external/services/migration_service.py —— Legacy 迁移分类（S10，总册 §116-117）。

分类：
- CLEAR_EXTERNAL：employee_type 明确含 part-time/contract/external → 外聘候选；
- POSSIBLE_EXTERNAL：contract 类型/名称含兼职外聘等 → 需人工确认；
- REGULAR_EMPLOYEE：正式员工（不迁移为外聘）；
- AMBIGUOUS：无法裁决 → 人工确认（§116，禁止自动"猜正确"）。

重复人迁移（§117）：不按姓名自动 merge；用 identity evidence + manual review。
"""

from __future__ import annotations

from dataclasses import dataclass, field

_EXTERNAL_KEYWORDS = ("part-time", "parttime", "兼职", "外聘", "external", "contract", "劳务", "产业", "客座", "荣誉")


@dataclass
class MigrationCandidate:
    legacy_employee_id: int
    employee_name: str = ""
    employee_type: str = ""
    classification: str = ""  # CLEAR_EXTERNAL / POSSIBLE_EXTERNAL / REGULAR_EMPLOYEE / AMBIGUOUS
    reasons: list = field(default_factory=list)


class MigrationClassificationService:
    def classify(
        self,
        *,
        legacy_employee_id: int,
        employee_type_text: str = "",
        contract_name: str = "",
        employee_name: str = "",
    ) -> MigrationCandidate:
        reasons: list[str] = []

        def _contains(text: str, keys) -> bool:
            lowered = (text or "").lower()
            return any(k.lower() in lowered for k in keys)

        if employee_type_text and _contains(employee_type_text, ("part-time", "parttime", "external", "contract")):
            reasons.append("employee_type 明确外部/兼职")
            classification = "CLEAR_EXTERNAL"
        elif _contains(employee_type_text, ("兼职", "外聘", "劳务")) or _contains(
            contract_name, ("兼职", "外聘", "劳务", "产业", "客座", "荣誉")
        ):
            reasons.append("employee_type/contract 含外部语义")
            classification = "POSSIBLE_EXTERNAL"
        elif employee_type_text and not _contains(employee_type_text, ("兼职", "外聘")):
            reasons.append("employee_type 为正式类型")
            classification = "REGULAR_EMPLOYEE"
        else:
            reasons.append("信息不足")
            classification = "AMBIGUOUS"

        return MigrationCandidate(
            legacy_employee_id=legacy_employee_id,
            employee_name=employee_name,
            employee_type=employee_type_text,
            classification=classification,
            reasons=reasons,
        )
