from django.db import migrations, models
import django.core.validators


class Migration(migrations.Migration):
    dependencies = [("employee", "0006_badge_id_unique_mysql_safe")]
    operations = [migrations.AlterField(
        model_name="employee", name="phone",
        field=models.CharField(max_length=25, blank=True, default="", validators=[
            django.core.validators.RegexValidator(regex=r"^\+?[\d\s\-\(\)]{7,20}$", message="Enter a valid phone number (7-20 characters, optional +).")
        ]),
    ), migrations.AlterField(
        model_name="employee", name="gender",
        field=models.CharField(max_length=10, blank=True, null=True, default=None,
            choices=[("male", "Male"), ("female", "Female"), ("other", "Other")]),
    )]
