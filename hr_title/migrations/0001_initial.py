import uuid

from django.db import migrations, models
import django.db.models.expressions


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="TitlePolicyVersion",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("tenant_id", models.PositiveBigIntegerField(db_index=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.PositiveBigIntegerField(blank=True, null=True)),
                ("updated_by", models.PositiveBigIntegerField(blank=True, null=True)),
                ("version_no", models.PositiveIntegerField(default=1)),
                ("status", models.CharField(db_index=True, default="DRAFT", max_length=32)),
                ("content_hash", models.CharField(blank=True, default="", max_length=64)),
                ("policy_code", models.CharField(max_length=64)),
                ("name", models.CharField(max_length=200)),
                ("title_series_code", models.CharField(blank=True, default="", max_length=64)),
                ("title_level_code", models.CharField(blank=True, default="", max_length=64)),
                ("track_code", models.CharField(blank=True, default="", max_length=64)),
                ("effective_from", models.DateField()),
                ("effective_to", models.DateField(blank=True, null=True)),
                ("published_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={"db_table": "hr13_title_policy_version"},
        ),
        migrations.CreateModel(
            name="TitleApplicationCase",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("tenant_id", models.PositiveBigIntegerField(db_index=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.PositiveBigIntegerField(blank=True, null=True)),
                ("updated_by", models.PositiveBigIntegerField(blank=True, null=True)),
                ("case_no", models.CharField(max_length=64)),
                ("person_id", models.UUIDField()),
                ("policy_version_id", models.UUIDField()),
                ("batch_no", models.CharField(max_length=64)),
                ("requested_title_code", models.CharField(max_length=64)),
                ("requested_title_name", models.CharField(blank=True, default="", max_length=200)),
                ("status", models.CharField(choices=[("DRAFT", "Draft"), ("SUBMITTED", "Submitted"), ("RETURNED", "Returned for correction"), ("ELIGIBLE", "Eligibility passed"), ("REJECTED", "Rejected"), ("WITHDRAWN", "Withdrawn"), ("UNDER_REVIEW", "Under review"), ("PROPOSED", "Proposed result"), ("PUBLICITY", "Publicity"), ("EFFECTIVE", "Effective"), ("REVOKED", "Revoked")], db_index=True, default="DRAFT", max_length=32)),
                ("submitted_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={"db_table": "hr13_title_application_case"},
        ),
        migrations.CreateModel(
            name="ProfessionalTitleResult",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("tenant_id", models.PositiveBigIntegerField(db_index=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.PositiveBigIntegerField(blank=True, null=True)),
                ("updated_by", models.PositiveBigIntegerField(blank=True, null=True)),
                ("result_no", models.CharField(max_length=64)),
                ("person_id", models.UUIDField()),
                ("application_case_id", models.UUIDField()),
                ("title_code", models.CharField(max_length=64)),
                ("title_name", models.CharField(max_length=200)),
                ("title_series_code", models.CharField(blank=True, default="", max_length=64)),
                ("title_level_code", models.CharField(blank=True, default="", max_length=64)),
                ("effective_from", models.DateField()),
                ("effective_to", models.DateField(blank=True, null=True)),
                ("status", models.CharField(choices=[("EFFECTIVE", "Effective"), ("REVISED", "Revised"), ("REVOKED", "Revoked")], db_index=True, default="EFFECTIVE", max_length=16)),
                ("supersedes_result_id", models.UUIDField(blank=True, null=True)),
            ],
            options={"db_table": "hr13_professional_title_result"},
        ),
        migrations.AddConstraint(
            model_name="titlepolicyversion",
            constraint=models.UniqueConstraint(fields=("tenant_id", "policy_code", "version_no"), name="uq_hr13_policy_tenant_code_ver"),
        ),
        migrations.AddConstraint(
            model_name="titlepolicyversion",
            constraint=models.CheckConstraint(condition=models.Q(("effective_to__isnull", True), ("effective_to__gt", django.db.models.expressions.F("effective_from")), _connector="OR"), name="ck_hr13_policy_effective_range"),
        ),
        migrations.AddIndex(
            model_name="titlepolicyversion",
            index=models.Index(fields=["tenant_id", "status"], name="idx_hr13_policy_tenant_status"),
        ),
        migrations.AddConstraint(
            model_name="titleapplicationcase",
            constraint=models.UniqueConstraint(fields=("tenant_id", "case_no"), name="uq_hr13_case_tenant_no"),
        ),
        migrations.AddIndex(
            model_name="titleapplicationcase",
            index=models.Index(fields=["tenant_id", "person_id", "status"], name="idx_hr13_case_tenant_person"),
        ),
        migrations.AddIndex(
            model_name="titleapplicationcase",
            index=models.Index(fields=["tenant_id", "batch_no", "status"], name="idx_hr13_case_tenant_batch"),
        ),
        migrations.AddConstraint(
            model_name="professionaltitleresult",
            constraint=models.UniqueConstraint(fields=("tenant_id", "result_no"), name="uq_hr13_result_tenant_no"),
        ),
        migrations.AddConstraint(
            model_name="professionaltitleresult",
            constraint=models.CheckConstraint(condition=models.Q(("effective_to__isnull", True), ("effective_to__gt", django.db.models.expressions.F("effective_from")), _connector="OR"), name="ck_hr13_result_effective_range"),
        ),
        migrations.AddIndex(
            model_name="professionaltitleresult",
            index=models.Index(fields=["tenant_id", "person_id", "status"], name="idx_hr13_result_tenant_person"),
        ),
    ]
