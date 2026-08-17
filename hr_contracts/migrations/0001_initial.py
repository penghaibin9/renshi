import uuid

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="HrContractAgreement",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("tenant_id", models.PositiveBigIntegerField(db_index=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.PositiveBigIntegerField(blank=True, null=True)),
                ("updated_by", models.PositiveBigIntegerField(blank=True, null=True)),
                ("agreement_no", models.CharField(max_length=64)),
                ("staff_id", models.UUIDField(db_index=True)),
                ("employment_relationship_id", models.UUIDField(db_index=True)),
                ("agreement_title", models.CharField(max_length=200)),
                ("agreement_type", models.CharField(max_length=50)),
                ("status", models.CharField(choices=[("DRAFT", "Draft"), ("WAITING_SIGNATURE", "Waiting signature"), ("SIGNED_WAITING_EFFECTIVE", "Signed, waiting effective"), ("ACTIVE", "Active"), ("EXPIRING", "Expiring"), ("RENEWAL_IN_PROGRESS", "Renewal in progress"), ("TERMINATED", "Terminated"), ("EXPIRED", "Expired"), ("ARCHIVED", "Archived")], db_index=True, default="DRAFT", max_length=32)),
                ("current_version_no", models.PositiveIntegerField(default=0)),
                ("legacy_contract_id", models.PositiveBigIntegerField(blank=True, null=True)),
            ],
            options={"db_table": "hr07_contract_agreement"},
        ),
        migrations.CreateModel(
            name="HrContractVersion",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("tenant_id", models.PositiveBigIntegerField(db_index=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.PositiveBigIntegerField(blank=True, null=True)),
                ("updated_by", models.PositiveBigIntegerField(blank=True, null=True)),
                ("version_no", models.PositiveIntegerField()),
                ("effective_from", models.DateField()),
                ("effective_to", models.DateField(blank=True, null=True)),
                ("signed_at", models.DateTimeField(blank=True, null=True)),
                ("signed_document_ref", models.CharField(blank=True, default="", max_length=255)),
                ("content_snapshot_json", models.JSONField(default=dict)),
                ("content_hash", models.CharField(max_length=64)),
                ("status", models.CharField(choices=[("DRAFT", "Draft"), ("SIGNED", "Signed"), ("EFFECTIVE", "Effective"), ("SUPERSEDED", "Superseded"), ("TERMINATED", "Terminated"), ("EXPIRED", "Expired")], db_index=True, default="DRAFT", max_length=20)),
                ("supersedes_version_id", models.UUIDField(blank=True, null=True)),
                ("source_business_type", models.CharField(blank=True, default="", max_length=50)),
                ("source_business_id", models.CharField(blank=True, default="", max_length=100)),
                ("agreement", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="versions", to="hr_contracts.hrcontractagreement")),
            ],
            options={"db_table": "hr07_contract_version"},
        ),
        migrations.CreateModel(
            name="HrContractCase",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("tenant_id", models.PositiveBigIntegerField(db_index=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.PositiveBigIntegerField(blank=True, null=True)),
                ("updated_by", models.PositiveBigIntegerField(blank=True, null=True)),
                ("case_no", models.CharField(max_length=64)),
                ("case_type", models.CharField(choices=[("SIGN", "Sign"), ("RENEW", "Renew"), ("CHANGE", "Change"), ("TERMINATE", "Terminate")], max_length=16)),
                ("status", models.CharField(choices=[("DRAFT", "Draft"), ("SUBMITTED", "Submitted"), ("RETURNED", "Returned"), ("APPROVED", "Approved"), ("REJECTED", "Rejected"), ("EFFECT_PENDING", "Waiting for contract effect"), ("EFFECTIVE", "Effective"), ("CANCELLED", "Cancelled")], db_index=True, default="DRAFT", max_length=20)),
                ("requested_effective_from", models.DateField(blank=True, null=True)),
                ("requested_effective_to", models.DateField(blank=True, null=True)),
                ("reason_code", models.CharField(blank=True, default="", max_length=50)),
                ("reason_text", models.TextField(blank=True, default="")),
                ("approved_at", models.DateTimeField(blank=True, null=True)),
                ("approved_by", models.PositiveBigIntegerField(blank=True, null=True)),
                ("effect_receipt_json", models.JSONField(blank=True, default=dict)),
                ("last_effect_error", models.TextField(blank=True, default="")),
                ("agreement", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="cases", to="hr_contracts.hrcontractagreement")),
            ],
            options={"db_table": "hr07_contract_case"},
        ),
        migrations.AddConstraint(
            model_name="hrcontractagreement",
            constraint=models.UniqueConstraint(fields=("tenant_id", "agreement_no"), name="uq_hr07_agree_tenant_no"),
        ),
        migrations.AddConstraint(
            model_name="hrcontractagreement",
            constraint=models.UniqueConstraint(fields=("tenant_id", "legacy_contract_id"), name="uq_hr07_agree_legacy"),
        ),
        migrations.AddIndex(
            model_name="hrcontractagreement",
            index=models.Index(fields=["tenant_id", "staff_id", "status"], name="idx_hr07_agree_staff"),
        ),
        migrations.AddIndex(
            model_name="hrcontractagreement",
            index=models.Index(fields=["tenant_id", "employment_relationship_id", "status"], name="idx_hr07_agree_rel"),
        ),
        migrations.AddConstraint(
            model_name="hrcontractversion",
            constraint=models.UniqueConstraint(fields=("tenant_id", "agreement", "version_no"), name="uq_hr07_ver_agree_no"),
        ),
        migrations.AddConstraint(
            model_name="hrcontractversion",
            constraint=models.CheckConstraint(condition=models.Q(("effective_to__isnull", True), ("effective_to__gt", models.F("effective_from")), _connector="OR"), name="ck_hr07_ver_date_range"),
        ),
        migrations.AddIndex(
            model_name="hrcontractversion",
            index=models.Index(fields=["tenant_id", "agreement", "status"], name="idx_hr07_ver_agree"),
        ),
        migrations.AddIndex(
            model_name="hrcontractversion",
            index=models.Index(fields=["tenant_id", "effective_to", "status"], name="idx_hr07_ver_expiry"),
        ),
        migrations.AddConstraint(
            model_name="hrcontractcase",
            constraint=models.UniqueConstraint(fields=("tenant_id", "case_no"), name="uq_hr07_case_tenant_no"),
        ),
        migrations.AddConstraint(
            model_name="hrcontractcase",
            constraint=models.CheckConstraint(condition=models.Q(("requested_effective_to__isnull", True), ("requested_effective_from__isnull", True), ("requested_effective_to__gt", models.F("requested_effective_from")), _connector="OR"), name="ck_hr07_case_date_range"),
        ),
        migrations.AddIndex(
            model_name="hrcontractcase",
            index=models.Index(fields=["tenant_id", "agreement", "status"], name="idx_hr07_case_agree"),
        ),
    ]
