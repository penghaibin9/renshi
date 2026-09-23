from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [("hr_staff", "0022_retirement_evidence_categories")]
    operations = [migrations.AddField(model_name="hrimportrow", name="result_ref",
                    field=models.CharField(max_length=64, blank=True, default=""))]
