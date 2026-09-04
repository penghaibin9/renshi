from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("hr_exit", "0011_retirement_archive_integrity")]

    operations = [
        migrations.AddField(
            model_name="retirementpolicy",
            name="transition_birth_start",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="retirementpolicy",
            name="delay_step_birth_months",
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="retirementpolicy",
            name="max_retirement_age_months",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddConstraint(
            model_name="retirementpolicy",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(
                        transition_birth_start__isnull=True,
                        delay_step_birth_months=0,
                        max_retirement_age_months__isnull=True,
                    )
                    | models.Q(
                        transition_birth_start__isnull=False,
                        delay_step_birth_months__gt=0,
                        max_retirement_age_months__gte=models.F("retirement_age_months"),
                    )
                ),
                name="ck_hr16_retire_transition_shape",
            ),
        ),
    ]
