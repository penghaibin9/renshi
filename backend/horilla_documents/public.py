"""Source-owned, metadata-only document evidence contract for HR consumers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from django.db.models import Q

from hr_staff.models import HrStaffMaster


PROVIDER_VERSION = "horilla-documents-approved-evidence-v1"


def _document_model():
    """Resolve the legacy document table only for a non-empty evidence read."""

    from horilla_documents.models import Document

    return Document


class DocumentEvidenceUnavailable(RuntimeError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class DocumentEvidenceRow:
    document_id: int
    staff_id: Any
    title: str
    request_title: str
    issue_date: date | None
    expiry_date: date | None

    def snapshot(self) -> dict:
        # Never expose the storage path or a reusable download URL through an
        # assessment evidence snapshot. Authorized download remains in the
        # source document domain.
        return {
            "sourceObjectType": "HorillaDocument",
            "sourceObjectId": str(self.document_id),
            "documentRef": f"horilla-document:{self.document_id}",
            "staffId": str(self.staff_id),
            "title": self.title,
            "requestTitle": self.request_title,
            "status": "APPROVED",
            "issueDate": self.issue_date.isoformat() if self.issue_date else None,
            "expiryDate": self.expiry_date.isoformat() if self.expiry_date else None,
        }


@dataclass(frozen=True)
class DocumentEvidence:
    rows: tuple[DocumentEvidenceRow, ...]
    missing_staff_ids: tuple[Any, ...]
    source_version: str = PROVIDER_VERSION


def _dedupe(values) -> tuple:
    result = []
    seen = set()
    for value in values:
        key = str(value)
        if key not in seen:
            seen.add(key)
            result.append(value)
    return tuple(result)


def get_approved_document_evidence(
    *,
    tenant_id: int,
    staff_ids: list[Any],
    as_of: date,
    source_version: str | None = None,
) -> DocumentEvidence:
    if not tenant_id:
        raise DocumentEvidenceUnavailable("TENANT_CONTEXT_REQUIRED", "tenant_id is required")
    if not isinstance(as_of, date):
        raise DocumentEvidenceUnavailable("AS_OF_REQUIRED", "as_of must be a date")
    if source_version not in (None, "", "v1", PROVIDER_VERSION):
        raise DocumentEvidenceUnavailable(
            "SOURCE_VERSION_UNSUPPORTED",
            f"unsupported document source version: {source_version}",
        )
    requested = _dedupe(staff_ids)
    if not requested:
        return DocumentEvidence((), ())

    mappings = list(
        HrStaffMaster.objects.filter(
            tenant_id=tenant_id,
            id__in=requested,
        ).values_list("id", "legacy_employee_id")
    )
    staff_by_legacy = {
        int(legacy_id): staff_id
        for staff_id, legacy_id in mappings
        if legacy_id is not None
    }
    mapped_staff_keys = {
        str(staff_id)
        for staff_id, legacy_id in mappings
        if legacy_id is not None
    }
    missing = tuple(value for value in requested if str(value) not in mapped_staff_keys)
    if not staff_by_legacy:
        return DocumentEvidence((), missing)

    Document = _document_model()
    documents = (
        Document.objects.filter(
            employee_id_id__in=staff_by_legacy,
            employee_id__employee_work_info__company_id_id=tenant_id,
            status="approved",
            document__isnull=False,
        )
        .exclude(document="")
        .filter(Q(issue_date__isnull=True) | Q(issue_date__lte=as_of))
        .filter(Q(expiry_date__isnull=True) | Q(expiry_date__gte=as_of))
        .select_related("document_request_id")
        .order_by("employee_id_id", "issue_date", "id")
    )
    rows = tuple(
        DocumentEvidenceRow(
            document_id=document.id,
            staff_id=staff_by_legacy[document.employee_id_id],
            title=document.title,
            request_title=(
                document.document_request_id.title
                if document.document_request_id is not None
                else ""
            ),
            issue_date=document.issue_date,
            expiry_date=document.expiry_date,
        )
        for document in documents
    )
    return DocumentEvidence(rows=rows, missing_staff_ids=missing)
