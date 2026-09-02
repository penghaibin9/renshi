import uuid

import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    # MySQL trigger DDL performs implicit commits.  Keep this migration
    # explicitly non-atomic so Django does not promise a transaction boundary
    # the database cannot provide.
    atomic = False

    dependencies = [("hr_payroll", "0010_trusted_input_snapshot_boundary")]

    operations = [
        migrations.CreateModel(
            name="ExternalSettlementBasisInput",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("tenant_id", models.PositiveBigIntegerField(db_index=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.PositiveBigIntegerField(blank=True, null=True)),
                ("updated_by", models.PositiveBigIntegerField(blank=True, null=True)),
                ("source_domain", models.CharField(default="HR08", max_length=16)),
                ("source_engagement_id", models.UUIDField()),
                ("source_version", models.PositiveIntegerField()),
                ("period_code", models.CharField(max_length=32)),
                ("verified_workload", models.DecimalField(decimal_places=2, max_digits=14)),
                ("eligible_items_json", models.JSONField(default=list)),
                ("policy_ref", models.CharField(blank=True, default="", max_length=64)),
                ("content_hash", models.CharField(max_length=64)),
                ("idempotency_key", models.CharField(max_length=128)),
                ("received_at", models.DateTimeField(default=django.utils.timezone.now)),
            ],
            options={
                "db_table": "hr15_external_settlement_input",
                "indexes": [
                    models.Index(
                        fields=["tenant_id", "period_code", "source_engagement_id"],
                        name="idx_hr15_ext_settle_period",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("tenant_id", "idempotency_key"),
                        name="uq_hr15_ext_settle_idem",
                    ),
                    models.UniqueConstraint(
                        fields=("tenant_id", "source_domain", "source_engagement_id", "period_code", "source_version"),
                        name="uq_hr15_ext_settle_ver",
                    ),
                ],
            },
        ),
        migrations.RunSQL(
            sql="""
                CREATE TRIGGER hr15_ext_settle_input_no_update
                BEFORE UPDATE ON hr15_external_settlement_input
                FOR EACH ROW
                SIGNAL SQLSTATE '45000'
                SET MESSAGE_TEXT = 'PAYROLL_EXTERNAL_SETTLEMENT_IMMUTABLE'
            """,
            reverse_sql="DROP TRIGGER IF EXISTS hr15_ext_settle_input_no_update",
        ),
        migrations.RunSQL(
            sql="""
                CREATE TRIGGER hr15_ext_settle_input_no_delete
                BEFORE DELETE ON hr15_external_settlement_input
                FOR EACH ROW
                SIGNAL SQLSTATE '45000'
                SET MESSAGE_TEXT = 'PAYROLL_EXTERNAL_SETTLEMENT_IMMUTABLE'
            """,
            reverse_sql="DROP TRIGGER IF EXISTS hr15_ext_settle_input_no_delete",
        ),
    ]
