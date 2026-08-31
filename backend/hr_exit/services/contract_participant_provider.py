"""HR16 participant adapter that verifies HR07 formal contract clearance."""

from __future__ import annotations

import hashlib
import json

from hr_contracts.models import HrContractAgreement
from hr_exit.services.participant_service import ExitParticipantUnavailable


_CLOSED = frozenset(
    {
        HrContractAgreement.Status.TERMINATED,
        HrContractAgreement.Status.EXPIRED,
        HrContractAgreement.Status.ARCHIVED,
    }
)


def exit_contract_participant_provider(
    *, tenant_id, case, effect, actor_user_id=None
):
    """Return a durable receipt only when HR07 owns no open agreement.

    HR16 deliberately does not manufacture or approve an HR07 termination case.
    If an agreement remains open, the saga is retryable after HR07 finishes its
    own approval/effect workflow.
    """

    agreements = list(
        HrContractAgreement.objects.filter(
            tenant_id=int(tenant_id),
            employment_relationship_id=case.employment_relationship_id,
        ).order_by("agreement_no", "current_version_no")
    )
    open_agreements = [row for row in agreements if row.status not in _CLOSED]
    if open_agreements:
        numbers = ",".join(row.agreement_no for row in open_agreements[:10])
        raise ExitParticipantUnavailable(
            "HR07 contract clearance is incomplete; open agreements: " + numbers
        )

    evidence = [
        {
            "agreementId": str(row.id),
            "agreementNo": row.agreement_no,
            "status": row.status,
            "currentVersionNo": row.current_version_no,
        }
        for row in agreements
    ]
    evidence_hash = hashlib.sha256(
        json.dumps(evidence, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    receipt_id = hashlib.sha256(
        f"{int(tenant_id)}:{effect.idempotency_key}:{evidence_hash}".encode("utf-8")
    ).hexdigest()
    return {
        "provider": "hr07.contract-clearance.1",
        "receiptId": receipt_id,
        "idempotencyKey": effect.idempotency_key,
        "employmentRelationshipId": str(case.employment_relationship_id),
        "agreementCount": len(agreements),
        "evidenceHash": evidence_hash,
        "agreements": evidence,
    }
