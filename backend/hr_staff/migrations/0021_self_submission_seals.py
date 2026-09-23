from django.db import migrations

TRIGGERS = {'hr03_material_submission_guard': "CREATE TRIGGER `hr03_material_submission_guard` BEFORE UPDATE ON `hr03_material_submission` FOR EACH ROW\nBEGIN\nIF NOT (NEW.tenant_id <=> OLD.tenant_id) OR NOT (NEW.request_id <=> OLD.request_id) OR NOT (NEW.material_version_id <=> OLD.material_version_id) OR NOT (NEW.revision <=> OLD.revision) OR NOT (NEW.submitted_by <=> OLD.submitted_by) OR NOT (NEW.evidence_hash <=> OLD.evidence_hash) OR OLD.reviewed_at IS NOT NULL THEN\nSIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'MATERIAL_SUBMISSION_IMMUTABLE'; END IF;\nEND", 'hr03_material_submission_no_delete': "CREATE TRIGGER `hr03_material_submission_no_delete` BEFORE DELETE ON `hr03_material_submission` FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'MATERIAL_SUBMISSION_DELETE_FORBIDDEN'", 'hr03_self_correction_source_guard': "CREATE TRIGGER `hr03_self_correction_source_guard` BEFORE UPDATE ON `hr_staff_hrcorrectioncase` FOR EACH ROW\nBEGIN\nIF OLD.source_channel = 'SELF' AND (NOT (NEW.source_channel <=> OLD.source_channel) OR NOT (NEW.tenant_id <=> OLD.tenant_id) OR NOT (NEW.staff_id_id <=> OLD.staff_id_id) OR NOT (NEW.source_snapshot_hash <=> OLD.source_snapshot_hash)) THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'SELF_CORRECTION_SOURCE_IMMUTABLE'; END IF;\nEND"}

TRIGGERS["hr03_self_correction_evidence_guard"] = """CREATE TRIGGER hr03_self_correction_evidence_guard
BEFORE UPDATE ON hr_staff_hrcorrectioncase FOR EACH ROW
BEGIN
 IF OLD.source_channel = 'SELF' AND OLD.status NOT IN ('DRAFT', 'RETURNED')
 AND (NOT (NEW.source_evidence_version_id <=> OLD.source_evidence_version_id)
 OR NOT (NEW.evidence_material_id <=> OLD.evidence_material_id)) THEN
 SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'SELF_CORRECTION_EVIDENCE_FROZEN'; END IF;
END"""
TRIGGERS["hr03_self_correction_item_guard"] = """CREATE TRIGGER hr03_self_correction_item_guard
BEFORE UPDATE ON hr_staff_hrcorrectionitem FOR EACH ROW
BEGIN
 IF EXISTS (SELECT 1 FROM hr_staff_hrcorrectioncase c WHERE c.id=OLD.case_id_id AND c.source_channel='SELF')
 AND (NOT (NEW.tenant_id <=> OLD.tenant_id) OR NOT (NEW.case_id_id <=> OLD.case_id_id)
 OR NOT (NEW.field_code <=> OLD.field_code) OR NOT (NEW.fact_id <=> OLD.fact_id)
 OR NOT (NEW.fact_type <=> OLD.fact_type) OR NOT (NEW.new_value_masked <=> OLD.new_value_masked)
 OR NOT (NEW.new_value_ref <=> OLD.new_value_ref) OR NOT (NEW.effective_date <=> OLD.effective_date)) THEN
 SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'SELF_CORRECTION_ITEM_FROZEN'; END IF;
END"""
TRIGGERS["hr03_self_correction_item_delete_guard"] = """CREATE TRIGGER hr03_self_correction_item_delete_guard
BEFORE DELETE ON hr_staff_hrcorrectionitem FOR EACH ROW
BEGIN
 IF EXISTS (SELECT 1 FROM hr_staff_hrcorrectioncase c WHERE c.id=OLD.case_id_id AND c.source_channel='SELF') THEN
 SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'SELF_CORRECTION_ITEM_DELETE_FORBIDDEN'; END IF;
END"""

TRIGGERS["hr03_self_correction_item_insert_guard"] = """CREATE TRIGGER hr03_self_correction_item_insert_guard
BEFORE INSERT ON hr_staff_hrcorrectionitem FOR EACH ROW
BEGIN
 IF EXISTS (SELECT 1 FROM hr_staff_hrcorrectioncase c WHERE c.id=NEW.case_id_id AND c.source_channel='SELF') THEN
 SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'SELF_CORRECTION_ITEM_INSERT_FORBIDDEN'; END IF;
END"""

def install(apps, schema_editor):
    if schema_editor.connection.vendor != "mysql":
        raise RuntimeError("MySQL-only migration; do not silently bypass database seals")
    for name, sql in TRIGGERS.items():
        schema_editor.execute("DROP TRIGGER IF EXISTS `" + name + "`")
        schema_editor.execute(sql)

def remove(apps, schema_editor):
    for name in TRIGGERS:
        schema_editor.execute("DROP TRIGGER IF EXISTS `" + name + "`")

class Migration(migrations.Migration):
    atomic = False
    dependencies = [('hr_staff', '0020_self_submissions')]
    operations = [migrations.RunPython(install, remove)]
