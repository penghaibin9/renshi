"""
hr_qualification/services/application_service.py —— 申报状态机服务（总册 §55/§66）。

状态转换：DRAFT → PRECHECKING → READY → SUBMITTED → FORMAL_REVIEW → ...
硬门：RETURNED ≠ NOT_RECOGNIZED；SUBMITTED 后证据包冻结。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from django.db import transaction

from hr_qualification.constants import ApplicationStatus
from hr_qualification.models import HrDoubleTeacherApplication
from hr_qualification.services.evidence_service import EvidenceAggregationService


class ApplicationError(Exception):
    pass


_TRANSITIONS: dict[str, set[str]] = {
    ApplicationStatus.DRAFT: {
        ApplicationStatus.PRECHECKING,
        ApplicationStatus.READY,
        ApplicationStatus.SUBMITTED,
        ApplicationStatus.WITHDRAWN,
        ApplicationStatus.CANCELLED,
    },
    ApplicationStatus.PRECHECKING: {
        ApplicationStatus.READY,
        ApplicationStatus.DRAFT,
    },
    ApplicationStatus.READY: {
        ApplicationStatus.SUBMITTED,
        ApplicationStatus.DRAFT,
        ApplicationStatus.WITHDRAWN,
    },
    ApplicationStatus.SUBMITTED: {
        ApplicationStatus.FORMAL_REVIEW,
        ApplicationStatus.WITHDRAWN,
    },
    ApplicationStatus.RETURNED: {
        ApplicationStatus.RESUBMITTED,
        ApplicationStatus.WITHDRAWN,
    },
    ApplicationStatus.RESUBMITTED: {
        ApplicationStatus.FORMAL_REVIEW,
        ApplicationStatus.WITHDRAWN,
    },
    ApplicationStatus.FORMAL_REVIEW: {
        ApplicationStatus.RETURNED,
        ApplicationStatus.ELIGIBLE,
        ApplicationStatus.PANEL_REVIEW,
    },
    ApplicationStatus.ELIGIBLE: {
        ApplicationStatus.PANEL_REVIEW,
    },
    ApplicationStatus.PANEL_REVIEW: {
        ApplicationStatus.RESULT_PENDING,
    },
    ApplicationStatus.RESULT_PENDING: {
        ApplicationStatus.RECOGNIZED,
        ApplicationStatus.NOT_RECOGNIZED,
        ApplicationStatus.OBJECTION,
    },
    ApplicationStatus.OBJECTION: {
        ApplicationStatus.RESULT_PENDING,
        ApplicationStatus.WITHDRAWN,
    },
}


class ApplicationService:
    """申报状态机服务。"""

    @staticmethod
    def transition(
        application: HrDoubleTeacherApplication,
        target_status: str,
    ) -> HrDoubleTeacherApplication:
        """状态转换（带 white-list 校验）。"""
        allowed = _TRANSITIONS.get(application.status, set())
        if target_status not in allowed:
            raise ApplicationError(
                f"Cannot transition from {application.status} to {target_status}. "
                f"Allowed: {allowed}"
            )

        old_status = application.status
        application.status = target_status

        if target_status == ApplicationStatus.SUBMITTED:
            application.submitted_at = datetime.now(timezone.utc)

        application.version += 1
        application.save()
        return application
