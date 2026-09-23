from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("hr_integration", "0002_ssologinevidence")]
    operations = [
        migrations.AddField(
            model_name="ssologinevidence",
            name="runtime_contract_hash",
            field=models.CharField(blank=True, db_index=True, default="", max_length=64),
        ),
    ]
