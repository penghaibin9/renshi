from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("hr_onboarding", "0011_merge_hr05_migration_branches"),
    ]

    operations = [
        migrations.RenameIndex(
            model_name="hronboardingoutboxevent",
            new_name="hr_onboardi_tenant__8d1b93_idx",
            old_name="hr_ob_outbox_tenant_status_at",
        ),
    ]
