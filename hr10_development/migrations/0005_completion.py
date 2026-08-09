# S5: completion + further_study
from django.db import migrations, models; import django.utils.timezone as tz

class Migration(migrations.Migration):
    dependencies=[("horilla_auth","__first__"),("hr10_development","0004_enrollment")]
    operations=[
        migrations.CreateModel("HrLearningParticipation",[
            ("id",models.BigAutoField(auto_created=True,primary_key=True,serialize=False)),
            ("tenant_id",models.BigIntegerField(db_index=True)),("created_at",models.DateTimeField(default=tz.now,editable=False)),("updated_at",models.DateTimeField(auto_now=True)),
            ("enrollment_id",models.BigIntegerField(db_index=True)),("session_id",models.BigIntegerField(blank=True,null=True)),("participation_type",models.CharField(max_length=16)),("source",models.CharField(max_length=32)),("started_at",models.DateTimeField(blank=True,null=True)),("ended_at",models.DateTimeField(blank=True,null=True)),("duration_minutes",models.IntegerField(blank=True,null=True)),("status",models.CharField(default="RECORDED",max_length=16)),("evidence_ref",models.CharField(blank=True,default="",max_length=256)),("verified_by",models.BigIntegerField(blank=True,null=True)),("verified_at",models.DateTimeField(blank=True,null=True))
        ],options={"db_table":"hr_learning_participation","verbose_name":"培训参与记录","verbose_name_plural":"培训参与记录"}),
        migrations.CreateModel("HrLearningCompletion",[
            ("id",models.BigAutoField(auto_created=True,primary_key=True,serialize=False)),
            ("tenant_id",models.BigIntegerField(db_index=True)),("created_at",models.DateTimeField(default=tz.now,editable=False)),("updated_at",models.DateTimeField(auto_now=True)),
            ("enrollment_id",models.BigIntegerField(db_index=True)),("program_version_id",models.BigIntegerField()),("completion_status",models.CharField(max_length=16)),("completed_at",models.DateTimeField(blank=True,null=True)),("verified_hours",models.DecimalField(blank=True,decimal_places=1,max_digits=8,null=True)),("verified_credits",models.DecimalField(blank=True,decimal_places=1,max_digits=6,null=True)),("score",models.DecimalField(blank=True,decimal_places=1,max_digits=5,null=True)),("evaluator_ref",models.CharField(blank=True,default="",max_length=128)),("evidence_package_id",models.CharField(blank=True,default="",max_length=256)),("verification_status",models.CharField(db_index=True,default="SELF_REPORTED",max_length=48)),("verified_by",models.BigIntegerField(blank=True,null=True)),("verified_at",models.DateTimeField(blank=True,null=True)),("revision_no",models.IntegerField(default=0)),("supersedes_id",models.BigIntegerField(blank=True,null=True)),("source",models.CharField(default="MANUAL",max_length=32)),("immutable_hash",models.CharField(blank=True,default="",max_length=128))
        ],options={"db_table":"hr_learning_completion","verbose_name":"培训完成","verbose_name_plural":"培训完成"}),
        migrations.CreateModel("HrFurtherStudyCase",[
            ("id",models.BigAutoField(auto_created=True,primary_key=True,serialize=False)),
            ("tenant_id",models.BigIntegerField(db_index=True)),("created_at",models.DateTimeField(default=tz.now,editable=False)),("updated_at",models.DateTimeField(auto_now=True)),
            ("staff_master_id",models.BigIntegerField(db_index=True)),("study_type",models.CharField(max_length=32)),("host_organization_id",models.BigIntegerField(blank=True,null=True)),("field_or_major",models.CharField(blank=True,default="",max_length=256)),("start_date",models.DateField()),("planned_end_date",models.DateField()),("full_time_or_part_time",models.CharField(default="FULL_TIME",max_length=16)),("funding_source",models.CharField(blank=True,default="",max_length=256)),("agreement_ref",models.CharField(blank=True,default="",max_length=256)),("leave_ref",models.CharField(blank=True,default="",max_length=256)),("lifecycle_status",models.CharField(db_index=True,default="IN_PROGRESS",max_length=32)),("version",models.IntegerField(default=1))
        ],options={"db_table":"hr_further_study_case","verbose_name":"进修案例","verbose_name_plural":"进修案例"}),
        migrations.CreateModel("HrFurtherStudyMilestone",[
            ("id",models.BigAutoField(auto_created=True,primary_key=True,serialize=False)),
            ("tenant_id",models.BigIntegerField(db_index=True)),("created_at",models.DateTimeField(default=tz.now,editable=False)),("updated_at",models.DateTimeField(auto_now=True)),
            ("case_id",models.BigIntegerField(db_index=True)),("milestone_type",models.CharField(max_length=32)),("planned_date",models.DateField()),("actual_date",models.DateField(blank=True,null=True)),("status",models.CharField(default="PENDING",max_length=16)),("evidence_refs",models.JSONField(blank=True,default=dict)),("verification_status",models.CharField(default="SELF_REPORTED",max_length=48)),("notes",models.TextField(blank=True,default=""))
        ],options={"db_table":"hr_further_study_milestone","verbose_name":"进修里程碑","verbose_name_plural":"进修里程碑"}),
    ]
