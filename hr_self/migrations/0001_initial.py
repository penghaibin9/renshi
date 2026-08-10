import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="SelfServiceCatalogItem",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("tenant_id", models.PositiveBigIntegerField(db_index=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.PositiveBigIntegerField(blank=True, null=True)),
                ("updated_by", models.PositiveBigIntegerField(blank=True, null=True)),
                ("service_code", models.CharField(max_length=64)),
                ("name", models.CharField(max_length=120)),
                ("source_domain", models.CharField(max_length=16)),
                ("action_key", models.CharField(max_length=64)),
                ("route", models.CharField(max_length=255)),
                ("audience", models.CharField(blank=True, default="SELF", max_length=64)),
                ("enabled", models.BooleanField(db_index=True, default=True)),
                ("sort_order", models.PositiveIntegerField(default=100)),
                ("search_keywords", models.CharField(blank=True, default="", max_length=500)),
            ],
            options={"db_table": "hr17_self_service_catalog"},
        ),
        migrations.CreateModel(
            name="SelfServicePinnedService",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("tenant_id", models.PositiveBigIntegerField(db_index=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.PositiveBigIntegerField(blank=True, null=True)),
                ("updated_by", models.PositiveBigIntegerField(blank=True, null=True)),
                ("staff_id", models.UUIDField()),
                ("service_code", models.CharField(max_length=64)),
                ("sort_order", models.PositiveIntegerField(default=100)),
            ],
            options={"db_table": "hr17_self_pinned_service"},
        ),
        migrations.AddConstraint(
            model_name="selfservicecatalogitem",
            constraint=models.UniqueConstraint(fields=("tenant_id", "service_code"), name="uq_hr17_catalog_tenant_code"),
        ),
        migrations.AddIndex(
            model_name="selfservicecatalogitem",
            index=models.Index(fields=["tenant_id", "enabled", "sort_order"], name="idx_hr17_catalog_tenant_enabled"),
        ),
        migrations.AddConstraint(
            model_name="selfservicepinnedservice",
            constraint=models.UniqueConstraint(fields=("tenant_id", "staff_id", "service_code"), name="uq_hr17_pin_tenant_staff_service"),
        ),
        migrations.AddIndex(
            model_name="selfservicepinnedservice",
            index=models.Index(fields=["tenant_id", "staff_id", "sort_order"], name="idx_hr17_pin_tenant_staff"),
        ),
    ]
