"""Bind an uploaded local document to the immutable signed contract version."""

from __future__ import annotations

import uuid

from django.db import transaction


LOCAL_DOCUMENT_PREFIX = "hr07-document:"


class ContractDocumentBindingError(ValueError):
    pass


@transaction.atomic
def bind_signed_document_reference(
    *, tenant_id: int, agreement_id, version, signed_document_ref: str, actor_id=None
) -> None:
    """Bind local references; external e-sign receipt references remain supported."""
    reference = str(signed_document_ref or "").strip()
    if not reference.startswith(LOCAL_DOCUMENT_PREFIX):
        return
    try:
        document_id = uuid.UUID(reference.removeprefix(LOCAL_DOCUMENT_PREFIX))
    except (TypeError, ValueError) as exc:
        raise ContractDocumentBindingError("本地合同文档编号无效") from exc

    from hr_contracts.models import HrAgreementDocument

    document = (
        HrAgreementDocument.objects.select_for_update()
        .filter(
            tenant_id=tenant_id,
            agreement_id=agreement_id,
            id=document_id,
        )
        .first()
    )
    if document is None:
        raise ContractDocumentBindingError("本地合同文档不存在或不属于当前合同")
    if document.document_type != HrAgreementDocument.DocumentType.SIGNED_CONTRACT:
        raise ContractDocumentBindingError("签署凭证必须引用正式合同 PDF")
    if document.version_id and document.version_id != version.id:
        raise ContractDocumentBindingError("合同文档已绑定其他正式版本")
    document.version = version
    document.signature_status = HrAgreementDocument.SignatureStatus.SIGNED
    document.updated_by = actor_id
    document.full_clean()
    document.save(
        update_fields=("version", "signature_status", "updated_by", "updated_at")
    )
