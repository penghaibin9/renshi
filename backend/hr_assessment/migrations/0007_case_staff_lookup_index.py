from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("hr_assessment", "0006_state_convergence_05")]

    operations = [
        migrations.AddIndex(
            model_name="hrassessmentcase",
            index=models.Index(
                fields=["tenant_id", "staff_id"],
                name="hr12_case_staff_id_idx",
            ),
        ),
    ]
