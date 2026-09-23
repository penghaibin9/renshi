"""Tenant-scoped HR09 authority cutover state.

HR09 uses the shared HR01 ``HrAuthorityCutover`` ledger instead of hiding
rollout state inside credential catalog rows.  A missing record is explicitly
LEGACY; database errors fail closed rather than pretending a switch succeeded.
"""

from __future__ import annotations

from django.db import DatabaseError, transaction


class QualificationAuthorityMode:
    LEGACY = "LEGACY"
    DUAL_READ_COMPARE = "DUAL_READ_COMPARE"
    HR09_AUTHORITY = "HR09_AUTHORITY"
    values = {LEGACY, DUAL_READ_COMPARE, HR09_AUTHORITY}


class QualificationAuthorityModeError(RuntimeError):
    pass


_DB_TO_PUBLIC = {
    "LEGACY_ONLY": QualificationAuthorityMode.LEGACY,
    "DUAL_READ_COMPARE": QualificationAuthorityMode.DUAL_READ_COMPARE,
    "AUTHORITY_ONLY": QualificationAuthorityMode.HR09_AUTHORITY,
}
_PUBLIC_TO_DB = {value: key for key, value in _DB_TO_PUBLIC.items()}


class QualificationAuthorityModeService:
    domain = "QUALIFICATION"

    @staticmethod
    def _model():
        from hr_control_center.models import HrAuthorityCutover

        return HrAuthorityCutover

    def get_mode(self, tenant_id: int) -> str:
        if not tenant_id:
            raise QualificationAuthorityModeError("tenant_id is required")
        try:
            row = self._model().objects.filter(
                tenant_id=int(tenant_id), domain=self.domain
            ).first()
        except DatabaseError as exc:
            raise QualificationAuthorityModeError(
                "HR09 authority state is temporarily unavailable"
            ) from exc
        if row is None:
            return QualificationAuthorityMode.LEGACY
        try:
            return _DB_TO_PUBLIC[row.mode]
        except KeyError as exc:
            raise QualificationAuthorityModeError(
                f"unsupported HR09 authority database mode: {row.mode}"
            ) from exc

    @transaction.atomic
    def record_cutover(
        self,
        *,
        tenant_id: int,
        mode: str,
        reason: str,
        cutover_by: str = "",
        verification_report_id: str = "",
    ):
        if mode not in QualificationAuthorityMode.values:
            raise QualificationAuthorityModeError(f"unsupported HR09 mode: {mode}")
        reason = str(reason or "").strip()
        if not reason:
            raise QualificationAuthorityModeError("cutover reason is required")
        verification_report_id = str(verification_report_id or "").strip()
        if mode == QualificationAuthorityMode.HR09_AUTHORITY and not verification_report_id:
            raise QualificationAuthorityModeError(
                "HR09_AUTHORITY requires a reconciliation verification report id"
            )
        model = self._model()
        row, _ = model.objects.update_or_create(
            tenant_id=int(tenant_id),
            domain=self.domain,
            defaults={
                "mode": _PUBLIC_TO_DB[mode],
                "reason": reason[:255],
                "cutover_by": str(cutover_by or "")[:128],
                "verification_report_id": verification_report_id[:64],
            },
        )
        return row
