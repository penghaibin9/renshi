from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("hr_staff", "0021_self_submission_seals")]

    operations = [
        migrations.AlterField(
            model_name="hrstaffmaterial",
            name="category_code",
            field=models.CharField(
                choices=[
                    ("IDENTITY", "Identity"),
                    ("EDUCATION", "Education"),
                    ("DEGREE", "Degree"),
                    ("TEACHER_QUALIFICATION", "Teacher Qualification"),
                    ("PROFESSIONAL_CERTIFICATE", "Professional Certificate"),
                    ("SKILL_CERTIFICATE", "Skill Certificate"),
                    ("EMPLOYMENT", "Employment"),
                    ("APPOINTMENT", "Appointment"),
                    ("CONTRACT_REFERENCE", "Contract Reference"),
                    ("HONOR", "Honor"),
                    ("CORRECTION_EVIDENCE", "Correction Evidence"),
                    ("RETIREMENT_NOTICE", "Retirement Notice"),
                    ("RETIREMENT_APPROVAL", "Retirement Approval"),
                    ("RETIREMENT_CONTRIBUTION", "Retirement Contribution Evidence"),
                    ("RETIREMENT_AGREEMENT", "Retirement Written Agreement"),
                    ("OTHER_HR", "Other HR"),
                ],
                default="OTHER_HR",
                max_length=32,
            ),
        ),
        migrations.AlterField(
            model_name="hrmaterialrequest",
            name="required_category_code",
            field=models.CharField(
                blank=True,
                choices=[
                    ("IDENTITY", "Identity"),
                    ("EDUCATION", "Education"),
                    ("DEGREE", "Degree"),
                    ("TEACHER_QUALIFICATION", "Teacher Qualification"),
                    ("PROFESSIONAL_CERTIFICATE", "Professional Certificate"),
                    ("SKILL_CERTIFICATE", "Skill Certificate"),
                    ("EMPLOYMENT", "Employment"),
                    ("APPOINTMENT", "Appointment"),
                    ("CONTRACT_REFERENCE", "Contract Reference"),
                    ("HONOR", "Honor"),
                    ("CORRECTION_EVIDENCE", "Correction Evidence"),
                    ("RETIREMENT_NOTICE", "Retirement Notice"),
                    ("RETIREMENT_APPROVAL", "Retirement Approval"),
                    ("RETIREMENT_CONTRIBUTION", "Retirement Contribution Evidence"),
                    ("RETIREMENT_AGREEMENT", "Retirement Written Agreement"),
                    ("OTHER_HR", "Other HR"),
                ],
                default="",
                max_length=32,
            ),
        ),
    ]
