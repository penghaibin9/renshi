from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("base", "0011_alter_companyleaves_options_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="PlatformTenantElevation",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("reason", models.TextField()),
                ("reference", models.CharField(blank=True, max_length=120)),
                (
                    "granted_at",
                    models.DateTimeField(default=django.utils.timezone.now, editable=False),
                ),
                ("expires_at", models.DateTimeField()),
                ("revoked_at", models.DateTimeField(blank=True, null=True)),
                ("revoked_reason", models.CharField(blank=True, max_length=255)),
                ("source_ip", models.GenericIPAddressField(blank=True, null=True)),
                ("request_id", models.CharField(blank=True, max_length=64)),
                ("user_agent_hash", models.CharField(blank=True, max_length=64)),
                (
                    "actor",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="platform_tenant_elevations",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "company",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="platform_access_elevations",
                        to="base.company",
                    ),
                ),
                (
                    "revoked_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="revoked_platform_tenant_elevations",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ("-granted_at", "-id"),
            },
        ),
        migrations.AddIndex(
            model_name="platformtenantelevation",
            index=models.Index(
                fields=["actor", "expires_at"], name="plat_el_actor_exp_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="platformtenantelevation",
            index=models.Index(
                fields=["company", "expires_at"], name="plat_el_comp_exp_idx"
            ),
        ),
    ]
