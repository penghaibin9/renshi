from django.db import migrations

TRIGGERS = {'hr16_flex_identity_guard': "CREATE TRIGGER hr16_flex_identity_guard BEFORE UPDATE ON hr16_retirement_flex_application FOR EACH ROW\nBEGIN\n IF (NOT (OLD.`tenant_id` <=> NEW.`tenant_id`) OR NOT (OLD.`staff_id` <=> NEW.`staff_id`) OR NOT (OLD.`person_id` <=> NEW.`person_id`) OR NOT (OLD.`employment_relationship_id` <=> NEW.`employment_relationship_id`) OR NOT (OLD.`precheck_id` <=> NEW.`precheck_id`) OR NOT (OLD.`parent_application_id` <=> NEW.`parent_application_id`) OR NOT (OLD.`mode` <=> NEW.`mode`) OR NOT (OLD.`requested_date` <=> NEW.`requested_date`) OR NOT (OLD.`created_by` <=> NEW.`created_by`) OR NOT (OLD.`request_hash` <=> NEW.`request_hash`) OR NOT (OLD.`idempotency_key` <=> NEW.`idempotency_key`) OR NOT (OLD.`authority_snapshot` <=> NEW.`authority_snapshot`)) OR (OLD.approved_at IS NOT NULL AND (NOT (OLD.`notice_date` <=> NEW.`notice_date`) OR NOT (OLD.`notice_material_version_id` <=> NEW.`notice_material_version_id`) OR NOT (OLD.`review_snapshot` <=> NEW.`review_snapshot`) OR NOT (OLD.`approved_by` <=> NEW.`approved_by`) OR NOT (OLD.`approved_at` <=> NEW.`approved_at`) OR NOT (OLD.`approval_hash` <=> NEW.`approval_hash`) OR NOT (OLD.`status` <=> NEW.`status`))) THEN\n  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'FLEX_APPROVAL_OR_IDENTITY_IMMUTABLE';\n END IF;\nEND", 'hr16_flex_no_delete': "CREATE TRIGGER hr16_flex_no_delete BEFORE DELETE ON hr16_retirement_flex_application FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'FLEX_APPLICATION_DELETE_FORBIDDEN'", 'hr16_flex_event_no_update': "CREATE TRIGGER hr16_flex_event_no_update BEFORE UPDATE ON hr16_retirement_flex_event FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'FLEX_EVENT_IMMUTABLE'", 'hr16_flex_event_no_delete': "CREATE TRIGGER hr16_flex_event_no_delete BEFORE DELETE ON hr16_retirement_flex_event FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'FLEX_EVENT_IMMUTABLE'"}

def install(apps, schema_editor):
    if schema_editor.connection.vendor != "mysql":
        raise RuntimeError("HR16 flexible retirement requires MySQL")
    for name, sql in TRIGGERS.items():
        schema_editor.execute("DROP TRIGGER IF EXISTS `" + name + "`")
        schema_editor.execute(sql)

def uninstall(apps, schema_editor):
    for name in TRIGGERS:
        schema_editor.execute("DROP TRIGGER IF EXISTS `" + name + "`")

class Migration(migrations.Migration):
    atomic = False
    dependencies = [("hr_exit", "0014_flexible_retirement_workflow")]
    operations = [migrations.RunPython(install, uninstall)]
