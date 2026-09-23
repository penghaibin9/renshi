"""Rewrap sensitive HR fields and searchable fingerprints before production go-live."""

from __future__ import annotations

from collections import Counter

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from horilla.security.field_keyring import parse_fernet_keyring
from hr_onboarding.services.security import (
    decrypt_sensitive_value,
    encrypt_sensitive_value,
    needs_sensitive_rewrap,
)
from hr_qualification.security import (
    certificate_no_hash,
    decrypt_certificate_no,
    encrypt_certificate_no,
    needs_certificate_rewrap,
)
from hr_recruitment.security import (
    candidate_id_hash,
    decrypt_candidate_national_id,
    encrypt_candidate_national_id,
    needs_candidate_rewrap,
)
from hr_staff.services.crypto import (
    decrypt_document_number,
    document_fingerprint,
    encrypt_document_number,
    needs_document_rewrap,
    normalize_document_number,
)


class Command(BaseCommand):
    help = (
        "Audit or rewrap HR03/HR04/HR05/HR09 high-sensitive fields onto the "
        "current production field-encryption/fingerprint keys."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="write the rewrapped ciphertext/fingerprint values",
        )
        parser.add_argument(
            "--check",
            action="store_true",
            help="exit non-zero when any row still needs rewrap or cannot be upgraded",
        )
        parser.add_argument(
            "--tenant",
            type=int,
            default=None,
            help="limit audit/rewrap to one tenant; omit for platform-wide scan",
        )

    def handle(self, *args, **options):
        raw_keys = str(getattr(settings, "FIELD_ENCRYPTION_KEYS", "") or "").strip()
        fingerprint_key = str(getattr(settings, "FIELD_FINGERPRINT_KEY", "") or "").strip()
        try:
            parse_fernet_keyring(raw_keys)
        except Exception as exc:  # noqa: BLE001
            raise CommandError(f"FIELD_ENCRYPTION_KEYS_INVALID: {exc}") from exc
        if len(fingerprint_key.encode("utf-8")) < 32:
            raise CommandError("FIELD_FINGERPRINT_KEY_INVALID")

        stats = Counter()
        apply = bool(options.get("apply"))
        tenant_id = options.get("tenant")
        if tenant_id is not None and int(tenant_id) <= 0:
            raise CommandError("--tenant must be a positive integer")
        tenant_id = int(tenant_id) if tenant_id is not None else None

        with transaction.atomic():
            self._hr03(stats, apply=apply, tenant_id=tenant_id)
            self._hr04(stats, apply=apply, tenant_id=tenant_id)
            self._hr05(stats, apply=apply, tenant_id=tenant_id)
            self._hr09(stats, apply=apply, tenant_id=tenant_id)
            if not apply:
                transaction.set_rollback(True)

        ordered = [
            "hr03_scanned", "hr03_rewrap", "hr03_failed",
            "hr04_scanned", "hr04_rewrap", "hr04_hash_only_unresolved", "hr04_failed",
            "hr05_scanned", "hr05_rewrap", "hr05_failed",
            "hr09_scanned", "hr09_rewrap", "hr09_failed",
        ]
        summary = " ".join(f"{name}={stats[name]}" for name in ordered)
        mode = "APPLIED" if apply else "AUDIT"
        self.stdout.write(f"HR_FIELD_SECURITY_{mode} {summary}")

        blockers = (
            stats["hr03_failed"]
            + stats["hr04_hash_only_unresolved"]
            + stats["hr04_failed"]
            + stats["hr05_failed"]
            + stats["hr09_failed"]
        )
        remaining = (
            stats["hr03_rewrap"]
            + stats["hr04_rewrap"]
            + stats["hr05_rewrap"]
            + stats["hr09_rewrap"]
        )
        if options.get("check") and (blockers or (remaining and not apply)):
            raise CommandError(
                f"HR_FIELD_SECURITY_NOT_READY blockers={blockers} pending_rewrap={remaining}"
            )
        if apply and blockers:
            raise CommandError(f"HR_FIELD_SECURITY_APPLY_INCOMPLETE blockers={blockers}")

    @staticmethod
    def _hr03(stats: Counter, *, apply: bool, tenant_id: int | None):
        from hr_staff.models import HrPersonIdentityDocument

        qs = HrPersonIdentityDocument.objects.exclude(document_number_ciphertext="")
        if tenant_id is not None:
            qs = qs.filter(tenant_id=tenant_id)
        for row in qs.iterator(chunk_size=500):
            stats["hr03_scanned"] += 1
            plain = decrypt_document_number(row.document_number_ciphertext)
            if not plain:
                stats["hr03_failed"] += 1
                continue
            normalized = normalize_document_number(plain)
            target_hash = document_fingerprint(row.tenant_id, normalized)
            needs = needs_document_rewrap(row.document_number_ciphertext) or row.document_number_fingerprint != target_hash
            if not needs:
                continue
            stats["hr03_rewrap"] += 1
            if apply:
                HrPersonIdentityDocument.objects.filter(pk=row.pk).update(
                    document_number_ciphertext=encrypt_document_number(row.tenant_id, normalized),
                    document_number_fingerprint=target_hash,
                )

    @staticmethod
    def _hr04(stats: Counter, *, apply: bool, tenant_id: int | None):
        from hr_recruitment.models import HrRecruitmentCandidate

        qs = HrRecruitmentCandidate.objects.exclude(national_id_hash="")
        if tenant_id is not None:
            qs = qs.filter(tenant_id=tenant_id)
        for row in qs.iterator(chunk_size=500):
            stats["hr04_scanned"] += 1
            if not row.national_id_cipher:
                stats["hr04_hash_only_unresolved"] += 1
                continue
            try:
                plain = decrypt_candidate_national_id(row.national_id_cipher)
            except Exception:  # noqa: BLE001
                stats["hr04_failed"] += 1
                continue
            target_hash = candidate_id_hash(row.tenant_id, plain)
            needs = needs_candidate_rewrap(row.national_id_cipher) or row.national_id_hash != target_hash
            if not needs:
                continue
            stats["hr04_rewrap"] += 1
            if apply:
                HrRecruitmentCandidate.objects.filter(pk=row.pk).update(
                    national_id_cipher=encrypt_candidate_national_id(plain),
                    national_id_hash=target_hash,
                )

    @staticmethod
    def _hr05(stats: Counter, *, apply: bool, tenant_id: int | None):
        from hr_onboarding.models import HrPrehireProfile

        qs = HrPrehireProfile.objects.all()
        if tenant_id is not None:
            qs = qs.filter(tenant_id=tenant_id)
        for row in qs.iterator(chunk_size=500):
            stats["hr05_scanned"] += 1
            if not row.bank_json:
                continue
            plain = decrypt_sensitive_value(row.bank_json)
            if not plain:
                stats["hr05_failed"] += 1
                continue
            if not needs_sensitive_rewrap(row.bank_json):
                continue
            stats["hr05_rewrap"] += 1
            if apply:
                HrPrehireProfile.objects.filter(pk=row.pk).update(
                    bank_json=encrypt_sensitive_value(plain)
                )

    @staticmethod
    def _hr09(stats: Counter, *, apply: bool, tenant_id: int | None):
        from hr_qualification.models import HrPersonCredential

        qs = HrPersonCredential.objects.filter(certificate_no_cipher__isnull=False)
        if tenant_id is not None:
            qs = qs.filter(tenant_id=tenant_id)
        for row in qs.iterator(chunk_size=500):
            stats["hr09_scanned"] += 1
            try:
                plain = decrypt_certificate_no(row.certificate_no_cipher)
            except Exception:  # noqa: BLE001
                stats["hr09_failed"] += 1
                continue
            target_hash = certificate_no_hash(plain, tenant_id=row.tenant_id)
            needs = needs_certificate_rewrap(row.certificate_no_cipher) or row.certificate_no_hash != target_hash
            if not needs:
                continue
            stats["hr09_rewrap"] += 1
            if apply:
                HrPersonCredential.objects.filter(pk=row.pk).update(
                    certificate_no_cipher=encrypt_certificate_no(plain),
                    certificate_no_hash=target_hash,
                )
