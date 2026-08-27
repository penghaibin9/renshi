from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("hr_contracts", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="hrcontractagreement",
            name="subject_type",
            field=models.CharField(
                choices=[
                    ("STAFF_EMPLOYMENT", "Staff employment"),
                    ("EXTERNAL_WORKFORCE", "External workforce"),
                ],
                db_index=True,
                default="STAFF_EMPLOYMENT",
                max_length=32,
            ),
        ),
        migrations.AddField(
            model_name="hrcontractagreement",
            name="subject_person_id",
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="hrcontractagreement",
            name="subject_reference_type",
            field=models.CharField(blank=True, default="", max_length=50),
        ),
        migrations.AddField(
            model_name="hrcontractagreement",
            name="subject_reference_id",
            field=models.CharField(blank=True, default="", max_length=100),
        ),
        migrations.AlterField(
            model_name="hrcontractagreement",
            name="staff_id",
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AlterField(
            model_name="hrcontractagreement",
            name="employment_relationship_id",
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.AddConstraint(
            model_name="hrcontractagreement",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(
                        subject_type="STAFF_EMPLOYMENT",
                        staff_id__isnull=False,
                        employment_relationship_id__isnull=False,
                    )
                    | (
                        models.Q(
                            subject_type="EXTERNAL_WORKFORCE",
                            staff_id__isnull=True,
                            employment_relationship_id__isnull=True,
                            subject_person_id__isnull=False,
                        )
                        & ~models.Q(subject_reference_type="")
                        & ~models.Q(subject_reference_id="")
                    )
                ),
                name="ck_hr07_agree_subject_shape",
            ),
        ),
        migrations.AddIndex(
            model_name="hrcontractagreement",
            index=models.Index(
                fields=[
                    "tenant_id",
                    "subject_type",
                    "subject_reference_type",
                    "subject_reference_id",
                ],
                name="idx_hr07_agree_subject",
            ),
        ),
    ]
