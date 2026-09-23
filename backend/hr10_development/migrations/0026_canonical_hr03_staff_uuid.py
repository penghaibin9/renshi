"""Add HR03 UUID identity columns to HR10 without rewriting business history.

This migration is deliberately schema-only.  MySQL DDL is not fully
transactional, so data validation/backfill and database guards live in later
migrations.  If a legacy identity is dirty, 0027 can fail and be retried after
repair without re-running partially committed ADD COLUMN operations.
"""
from django.db import migrations, models


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("hr10_development", "0025_import_claim_lease_and_execution"),
        ("hr_staff", "0022_retirement_evidence_categories"),
    ]

    operations = [
        migrations.AddField(
            model_name="hrdevelopmentplan",
            name="staff_master_uuid",
            field=models.UUIDField(blank=True, db_index=True, null=True, verbose_name="HR03 教职工 UUID"),
        ),
        migrations.AddField(
            model_name="hrtrainingrequest",
            name="staff_master_uuid",
            field=models.UUIDField(blank=True, db_index=True, null=True, verbose_name="HR03 教职工 UUID"),
        ),
        migrations.AddField(
            model_name="hrlearningenrollment",
            name="staff_master_uuid",
            field=models.UUIDField(blank=True, db_index=True, null=True, verbose_name="HR03 教职工 UUID"),
        ),
        migrations.AddField(
            model_name="hrdevelopmentneed",
            name="staff_master_uuid",
            field=models.UUIDField(blank=True, db_index=True, null=True, verbose_name="HR03 教职工 UUID"),
        ),
        migrations.AddField(
            model_name="hrfurtherstudycase",
            name="staff_master_uuid",
            field=models.UUIDField(blank=True, db_index=True, null=True, verbose_name="HR03 教职工 UUID"),
        ),
        migrations.AddField(
            model_name="hrenterprisepracticeassignment",
            name="staff_master_uuid",
            field=models.UUIDField(blank=True, db_index=True, null=True, verbose_name="HR03 教职工 UUID"),
        ),
        migrations.AddField(
            model_name="hrdevelopmentoutput",
            name="staff_master_uuid",
            field=models.UUIDField(blank=True, db_index=True, null=True, verbose_name="HR03 教职工 UUID"),
        ),
        migrations.AddField(
            model_name="hrdevelopmentfact",
            name="staff_master_uuid",
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="hrdevelopmentmetricledger",
            name="staff_master_uuid",
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="hrdevelopmentriskcase",
            name="staff_master_uuid",
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AlterField(
            model_name="hrtrainingrequest",
            name="staff_master_id",
            field=models.BigIntegerField(blank=True, db_index=True, null=True, verbose_name="教职工 ID"),
        ),
        migrations.AlterField(
            model_name="hrlearningenrollment",
            name="staff_master_id",
            field=models.BigIntegerField(blank=True, db_index=True, null=True, verbose_name="教职工 ID"),
        ),
        migrations.AlterField(
            model_name="hrfurtherstudycase",
            name="staff_master_id",
            field=models.BigIntegerField(blank=True, db_index=True, null=True, verbose_name="兼容旧 Employee ID"),
        ),
        migrations.AlterField(
            model_name="hrenterprisepracticeassignment",
            name="staff_master_id",
            field=models.BigIntegerField(blank=True, db_index=True, null=True),
        ),
        migrations.AlterField(
            model_name="hrdevelopmentoutput",
            name="staff_master_id",
            field=models.BigIntegerField(blank=True, db_index=True, null=True),
        ),
        migrations.AlterField(
            model_name="hrdevelopmentfact",
            name="staff_master_id",
            field=models.BigIntegerField(blank=True, db_index=True, null=True),
        ),
        migrations.AlterField(
            model_name="hrdevelopmentmetricledger",
            name="staff_master_id",
            field=models.BigIntegerField(blank=True, db_index=True, null=True),
        ),
    ]
