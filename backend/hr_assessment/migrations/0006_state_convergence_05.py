import django.db.models.deletion
from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [('hr_assessment', '0005_state_convergence_04')]
    operations = [
        migrations.AlterField(model_name='hrtermassessmentcase', name='annual_result_refs_json', field=models.JSONField(default=list, verbose_name='年度结果引用')),
        migrations.AlterField(model_name='hrtermassessmentcase', name='term_duty_snapshot_json', field=models.JSONField(default=dict, verbose_name='聘期职责快照')),
        migrations.AlterField(model_name='hrtermassessmentcase', name='term_end', field=models.DateField(verbose_name='聘期结束')),
        migrations.AlterField(model_name='hrtermassessmentcase', name='term_goal_snapshot_json', field=models.JSONField(default=dict, verbose_name='聘期目标快照')),
        migrations.AlterField(model_name='hrtermassessmentcase', name='term_id', field=models.UUIDField(verbose_name='HR07 Term ID')),
        migrations.AlterField(model_name='hrtermassessmentcase', name='term_start', field=models.DateField(verbose_name='聘期开始')),
        migrations.AlterUniqueTogether(name='hrassessmentpopulationsnapshot', unique_together={('cycle', 'staff_id')}),
        migrations.AlterUniqueTogether(name='hrgoalassignment', unique_together={('goal', 'staff_id')}),
        migrations.AlterUniqueTogether(name='hrgoalversion', unique_together={('goal', 'version_no')}),
        migrations.AlterUniqueTogether(name='hrmultiraterfeedback', unique_together={('session', 'reviewer_staff_id')}),
        migrations.AddIndex(model_name='hrassessmentcycle', index=models.Index(fields=['tenant_id', 'assessment_type', 'lifecycle_status'], name='hr_assessme_tenant__5beb97_idx')),
        migrations.AddIndex(model_name='hrassessmentevidenceref', index=models.Index(fields=['case_id', 'indicator_id'], name='hr_assessme_case_id_a53870_idx')),
        migrations.AddIndex(model_name='hrassessmentevidenceref', index=models.Index(fields=['source_object_type', 'source_object_id'], name='hr_assessme_source__ef54e2_idx')),
        migrations.AddIndex(model_name='hrassessmentpopulationsnapshot', index=models.Index(fields=['cycle', 'org_id'], name='hr_assessme_cycle_i_f627dc_idx')),
        migrations.AddIndex(model_name='hrassessmentpopulationsnapshot', index=models.Index(fields=['cycle', 'included'], name='hr_assessme_cycle_i_59f4b0_idx')),
        migrations.AddIndex(model_name='hrfinalassessmentresult', index=models.Index(fields=['tenant_id', 'assessment_type', 'status'], name='hr_assessme_tenant__5eb2ea_idx')),
        migrations.AddIndex(model_name='hrfinalassessmentresult', index=models.Index(fields=['tenant_id', 'grade_code', 'finalized_at'], name='hr_assessme_tenant__e9c1f3_idx')),
        migrations.AddIndex(model_name='hrresultapplicationledger', index=models.Index(fields=['consumer_domain', 'result_version'], name='hr_assessme_consume_a9c4b8_idx')),
    ]
