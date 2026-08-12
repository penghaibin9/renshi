from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.db import migrations


def _fernet(tenant_id: int) -> Fernet:
    source = getattr(settings, "HR09_CERTIFICATE_ENCRYPTION_KEY", "") or settings.SECRET_KEY
    material = f"{source}:hr09:certificate:{int(tenant_id)}".encode("utf-8")
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(material).digest()))


def encrypt_existing(apps, schema_editor):
    Credential = apps.get_model("hr_qualification", "HrPersonCredential")
    qs = Credential.objects.exclude(certificate_no_cipher__isnull=True)
    for row in qs.iterator(chunk_size=500):
        if not row.certificate_no_cipher:
            continue
        raw = bytes(row.certificate_no_cipher)
        tenant_fernet = _fernet(row.tenant_id)
        if raw.startswith(b"gAAAA"):
            # Do not trust the Fernet-looking prefix by itself. Legacy plaintext
            # can start with the same characters; skip only authenticated tokens
            # that are already decryptable with this tenant's key.
            try:
                tenant_fernet.decrypt(raw)
            except InvalidToken:
                pass
            else:
                continue
        row.certificate_no_cipher = tenant_fernet.encrypt(raw)
        row.save(update_fields=["certificate_no_cipher"])


class Migration(migrations.Migration):
    dependencies = [("hr_qualification", "0004_alter_hrdoubleteacherrule_dimension_code")]
    operations = [migrations.RunPython(encrypt_existing, migrations.RunPython.noop)]