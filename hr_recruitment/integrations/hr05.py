"""Canonical HR04 -> HR05 onboarding consumer for W-A.

The recruitment domain owns the decision to hand an approved hire off, while
HR05 owns onboarding-case creation.  This adapter is intentionally thin: it
maps authoritative HR04 facts into CaseService.create_case_from_handoff and
returns the HR05 case id.  It never creates HR03 staff facts directly and it
never commits HR02 capacity; HR05 ActivationService owns those later steps.
"""

from __future__ import annotations

from typing import Optional

from hr_recruitment.constants import OfferStatus


class Hr05OnboardingConsumerError(Exception):
    """HR04 could not complete the canonical HR05 handoff."""


class Hr05OnboardingConsumer:
    """Production consumer used by HandoffService.

    Replays are delegated to HR05 CaseService. If its cache entry has expired
    but the tenant-scoped source-unique onboarding case still exists, the DB
    Authority row is recovered instead of turning a successful earlier create
    into a permanent duplicate failure.
    """

    def __init__(self, *, actor_user_id: Optional[int] = None):
        self.actor_user_id = actor_user_id

    def handle(
        self,
        *,
        tenant_id: int,
        proposed_hire_id: str,
        idempotency_key: str,
    ) -> str:
        if not tenant_id:
            raise Hr05OnboardingConsumerError("tenant_id is required")

        from hr_onboarding.api.exceptions import OnboardingCaseDuplicateError
        from hr_onboarding.models import HrOnboardingCase
        from hr_onboarding.services.case_service import CaseService
        from hr_recruitment.models import HrProposedHire, HrRecruitmentOffer

        proposed = (
            HrProposedHire.objects.select_related(
                "application_id__candidate_id",
                "recruitment_position_id",
            )
            .filter(tenant_id=tenant_id, id=proposed_hire_id)
            .first()
        )
        if proposed is None:
            raise Hr05OnboardingConsumerError("proposed hire not found in tenant")

        offer = (
            HrRecruitmentOffer.objects.filter(
                tenant_id=tenant_id,
                proposed_hire_id=proposed,
                status=OfferStatus.ACCEPTED,
            )
            .order_by("-accepted_at", "-created_at")
            .first()
        )
        if offer is None:
            raise Hr05OnboardingConsumerError("accepted offer is required for HR05 handoff")

        application = proposed.application_id
        candidate = application.candidate_id if application else None
        position = proposed.recruitment_position_id

        reservation_id = proposed.reservation_id or None
        if reservation_id is not None:
            try:
                reservation_id = int(reservation_id)
            except (TypeError, ValueError) as exc:
                raise Hr05OnboardingConsumerError("invalid HR02 reservation id") from exc

        request = {
            "tenant_id": tenant_id,
            "source_type": "HR04_HIRE",
            "source_id": str(proposed.id),
            "hr04_proposed_hire_id": str(proposed.id),
            "hr04_application_id": str(application.id),
            "position_reservation_id": reservation_id,
            "planned_organization_id": position.organization_id,
            "planned_post_catalog_id": position.post_catalog_id,
            "planned_position_id": position.position_id,
            "employment_type": offer.employment_type or "FULL_TIME",
            "staff_category": "TEACHER",
            "expected_report_date": offer.expected_report_date,
            "legal_name": candidate.legal_name if candidate else "",
            "preferred_name": "",
        }

        service = CaseService(
            tenant_id=tenant_id,
            actor_user_id=self.actor_user_id,
        )
        try:
            result = service.create_case_from_handoff(
                request,
                idempotency_key,
            )
        except OnboardingCaseDuplicateError as exc:
            # Cache is not Authority. A previous HR05 create may have committed
            # while its cache entry was evicted before HR04 sealed the handoff.
            # Recover only the exact same tenant + HR04 source tuple; never turn
            # an unrelated duplicate into a successful replay.
            existing = HrOnboardingCase.objects.filter(
                tenant_id=tenant_id,
                source_type="HR04_HIRE",
                source_id=str(proposed.id),
                hr04_proposed_hire_id=str(proposed.id),
                hr04_application_id=str(application.id),
            ).first()
            if existing is None:
                raise Hr05OnboardingConsumerError(
                    "duplicate HR05 onboarding case could not be resolved to the same HR04 source"
                ) from exc
            return str(existing.id)

        case_id = result.get("case_id") if isinstance(result, dict) else None
        if not case_id:
            raise Hr05OnboardingConsumerError("HR05 handoff did not return an onboarding case")
        return str(case_id)
