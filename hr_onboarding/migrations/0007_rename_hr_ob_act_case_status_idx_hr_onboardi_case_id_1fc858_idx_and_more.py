# Restored from the deterministic Django 5.2 index-name transition for HR05.
# This node also joins the two historical HR05 migration branches before 0008.

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("hr_onboarding", "0004_hronboardingauthoritymode"),
        ("hr_onboarding", "0006_hronboardingpermissionmeta"),
    ]

    operations = [
        migrations.RenameIndex(
            model_name="hractivationattempt",
            new_name="hr_onboardi_case_id_1fc858_idx",
            old_name="hr_ob_act_case_status_idx",
        ),
        migrations.RenameIndex(
            model_name="hronboardingauditevent",
            new_name="hr_onboardi_tenant__d03928_idx",
            old_name="hr_ob_audit_tenant_case_at",
        ),
        migrations.RenameIndex(
            model_name="hronboardingauditevent",
            new_name="hr_onboardi_tenant__79b3ec_idx",
            old_name="hr_ob_audit_tenant_action_idx",
        ),
        migrations.RenameIndex(
            model_name="hronboardingcase",
            new_name="hr_onboardi_tenant__d64ce9_idx",
            old_name="hr_ob_case_tenant_status_idx",
        ),
        migrations.RenameIndex(
            model_name="hronboardingcase",
            new_name="hr_onboardi_tenant__36de47_idx",
            old_name="hr_ob_case_tenant_report_idx",
        ),
        migrations.RenameIndex(
            model_name="hronboardingcase",
            new_name="hr_onboardi_tenant__59ca36_idx",
            old_name="hr_ob_case_tenant_stage_idx",
        ),
        migrations.RenameIndex(
            model_name="hronboardingmaterial",
            new_name="hr_onboardi_case_id_b7dc0b_idx",
            old_name="hr_ob_mat_case_status_idx",
        ),
        migrations.RenameIndex(
            model_name="hronboardingoutboxevent",
            new_name="hr_onboardi_tenant__8d1b93_idx",
            old_name="hr_ob_outbox_tenant_status_at",
        ),
        migrations.RenameIndex(
            model_name="hrprobationcase",
            new_name="hr_onboardi_staff_m_d63c4a_idx",
            old_name="hr_ob_prob_staff_status_idx",
        ),
        migrations.RenameIndex(
            model_name="hrprovisioningrequest",
            new_name="hr_onboardi_case_id_4ee4ac_idx",
            old_name="hr_ob_prov_case_status_idx",
        ),
        migrations.RenameIndex(
            model_name="hrprovisioningrequest",
            new_name="hr_onboardi_target__f3707d_idx",
            old_name="hr_ob_prov_target_status_idx",
        ),
        migrations.RenameIndex(
            model_name="hronboardingstagetransition",
            new_name="hr_onboardi_case_id_384700_idx",
            old_name="hr_ob_trans_case_at_idx",
        ),
        migrations.RenameIndex(
            model_name="hronboardingtaskinstance",
            new_name="hr_onboardi_case_id_06871b_idx",
            old_name="hr_ob_task_case_status_idx",
        ),
        migrations.RenameIndex(
            model_name="hronboardingtaskinstance",
            new_name="hr_onboardi_assigne_ccc7f2_idx",
            old_name="hr_ob_task_assignee_idx",
        ),
        migrations.RenameIndex(
            model_name="hronboardingtemplate",
            new_name="hr_onboardi_tenant__778b80_idx",
            old_name="hr_ob_tpl_tenant_status_idx",
        ),
    ]
