import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [('hr10_development', '0019_state_convergence_05')]
    operations = [
        migrations.AddIndex(model_name='hrlearningprogramversion', index=models.Index(fields=['program_id', 'status'], name='hr_learning_program_c6672e_idx')),
        migrations.AddIndex(model_name='hrtrainingrequest', index=models.Index(fields=['tenant_id', 'lifecycle_status'], name='hr_training_tenant__6f4bdf_idx')),
        migrations.AddIndex(model_name='hrtrainingrequest', index=models.Index(fields=['staff_master_id', 'lifecycle_status'], name='hr_training_staff_m_7eafc9_idx')),
        migrations.AddIndex(model_name='hrtrainingrequest', index=models.Index(fields=['offering_id', 'lifecycle_status'], name='hr_training_offerin_d3b134_idx')),
        migrations.AddConstraint(model_name='hrdurationledger', constraint=models.CheckConstraint(condition=models.Q(('raw_hours__gte', 0)), name='duration_raw_hours_non_negative')),
        migrations.AddConstraint(model_name='hrenterprisepracticeattendancefact', constraint=models.CheckConstraint(condition=models.Q(('duration_minutes__gte', 0)), name='attendance_duration_non_negative')),
        migrations.AddConstraint(model_name='hrlearningoffering', constraint=models.CheckConstraint(condition=models.Q(('capacity__gte', 0)), name='offering_capacity_non_negative')),
        migrations.AddConstraint(model_name='hrlearningoffering', constraint=models.CheckConstraint(condition=models.Q(('waitlist_capacity__gte', 0)), name='offering_waitlist_non_negative')),
    ]
