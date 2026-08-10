import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="ExitCase",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("tenant_id", models.PositiveBigIntegerField(db_index=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.PositiveBigIntegerField(blank=True, null=True)),
                ("updated_by", models.PositiveBigIntegerField(blank=True, null=True)),
                ("case_no", models.CharField(max_length=64)),
                ("person_id", models.UUIDField()),
                ("employment_relationship_id", models.UUIDField()),
                ("exit_type", models.CharField(choices=[("RESIGNATION", "Resignation"), ("TRANSFER_OUT", "Transfer out"), ("CONTRACT_END", "Contract end"), ("TERMINATION", "Termination"), ("RETIREMENT", "Retirement")], max_length=24)),
                ("status", models.CharField(choices=[("DRAFT", "Draft"), ("SUBMITTED", "Submitted"), ("RETURNED", "Returned for correction"), ("APPROVED", "Approved"), ("REJECTED", "Rejected"), ("HANDOVER", "Handover"), ("SETTLEMENT", "Settlement"), ("EFFECTIVE", "Effective"), ("CANCELLED", "Cancelled")], db_index=True, default="DRAFT", max_length=24)),
                ("requested_date", models.DateField(blank=True, null=True)),
                ("last_working_date", models.DateField(blank=True, null=True)),
                ("planned_employment_end_date", models.DateField(blank=True, null=True)),
                ("planned_access_end_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={"db_table": "hr16_exit_case"},
        ),
        migrations.CreateModel(
            name="ExitFact",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("tenant_id", models.PositiveBigIntegerField(db_index=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.PositiveBigIntegerField(blank=True, null=True)),
                ("updated_by", models.PositiveBigIntegerField(blank=True, null=True)),
                ("fact_no", models.CharField(max_length=64)),
                ("person_id", models.UUIDField()),
                ("employment_relationship_id", models.UUIDField()),
                ("source_case_id", models.UUIDField()),
                ("exit_type", models.CharField(choices=[("RESIGNATION", "Resignation"), ("TRANSFER_OUT", "Transfer out"), ("CONTRACT_END", "Contract end"), ("TERMINATION", "Termination"), ("RETIREMENT", "Retirement")], max_length=24)),
                ("employment_end_date", models.DateField()),
                ("last_working_date", models.DateField(blank=True, null=True)),
                ("access_end_at", models.DateTimeField(blank=True, null=True)),
                ("status", models.CharField(choices=[("EFFECTIVE", "Effective"), ("REVISED", "Revised"), ("REVOKED", "Revoked")], db_index=True, default="EFFECTIVE", max_length=16)),
                ("supersedes_fact_id", models.UUIDField(blank=True, null=True)),
            ],
            options={"db_table": "hr16_exit_fact"},
        ),
        migrations.CreateModel(
            name="RetirementFact",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("tenant_id", models.PositiveBigIntegerField(db_index=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.PositiveBigIntegerField(blank=True, null=True)),
                ("updated_by", models.PositiveBigIntegerField(blank=True, null=True)),
                ("fact_no", models.CharField(max_length=64)),
                ("person_id", models.UUIDField()),
                ("exit_fact_id", models.UUIDField()),
                ("retirement_type", models.CharField(max_length=32)),
                ("statutory_date", models.DateField(blank=True, null=True)),
                ("effective_date", models.DateField()),
                ("pension_processing_status", models.CharField(choices=[("NOT_STARTED", "Not started"), ("IN_PROGRESS", "In progress"), ("COMPLETED", "Completed")], db_index=True, default="NOT_STARTED", max_length=16)),
                ("status", models.CharField(choices=[("EFFECTIVE", "Effective"), ("REVISED", "Revised"), ("REVOKED", "Revoked")], db_index=True, default="EFFECTIVE", max_length=16)),
                ("supersedes_fact_id", models.UUIDField(blank=True, null=True)),
            ],
            options={"db_table": "hr16_retirement_fact"},
        ),
        migrations.AddConstraint(
            model_name="exitcase",
            constraint=models.UniqueConstraint(fields=("tenant_id", "case_no"), name="uq_hr16_case_tenant_no"),
        ),
        migrations.AddIndex(
            model_name="exitcase",
            index=models.Index(fields=["tenant_id", "person_id", "status"], name="idx_hr16_case_tenant_person"),
        ),
        migrations.AddConstraint(
            model_name="exitfact",
            constraint=models.UniqueConstraint(fields=("tenant_id", "fact_no"), name="uq_hr16_exit_fact_tenant_no"),
        ),
        migrations.AddIndex(
            model_name="exitfact",
            index=models.Index(fields=["tenant_id", "person_id", "status"], name="idx_hr16_exit_fact_person"),
        ),
        migrations.AddConstraint(
            model_name="retirementfact",
            constraint=models.UniqueConstraint(fields=("tenant_id", "fact_no"), name="uq_hr16_retire_fact_tenant_no"),
        ),
        migrations.AddIndex(
            model_name="retirementfact",
            index=models.Index(fields=["tenant_id", "person_id", "status"], name="idx_hr16_retire_fact_person"),
        ),
    ]
