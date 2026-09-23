"""Install retry-safe canonical identity guards after HR10 UUID backfill."""
from django.db import migrations, models


ENROLLMENT_CONSTRAINT = "uq_hr10_enroll_offering_staff_uuid"
FACT_UUID_INDEX = "hr_dev_fact_uuid_type_valid_idx"
IDENTITY_CHECKS = (
    ("HrTrainingRequest", "ck_hr10_request_staff_identity"),
    ("HrLearningEnrollment", "ck_hr10_enroll_staff_identity"),
    ("HrFurtherStudyCase", "ck_hr10_study_staff_identity"),
    ("HrEnterprisePracticeAssignment", "ck_hr10_practice_staff_identity"),
    ("HrDevelopmentOutput", "ck_hr10_output_staff_identity"),
    ("HrDevelopmentFact", "ck_hr10_fact_staff_identity"),
    ("HrDevelopmentMetricLedger", "ck_hr10_metric_staff_identity"),
)


def _constraints(schema_editor, table_name):
    with schema_editor.connection.cursor() as cursor:
        return schema_editor.connection.introspection.get_constraints(cursor, table_name)


def _identity_check(name):
    return models.CheckConstraint(
        condition=(
            models.Q(staff_master_uuid__isnull=False)
            | models.Q(staff_master_id__isnull=False)
        ),
        name=name,
    )


def add_identity_guards(apps, schema_editor):
    Enrollment = apps.get_model("hr10_development", "HrLearningEnrollment")
    Fact = apps.get_model("hr10_development", "HrDevelopmentFact")

    names = _constraints(schema_editor, Enrollment._meta.db_table)
    if ENROLLMENT_CONSTRAINT not in names:
        schema_editor.add_constraint(
            Enrollment,
            models.UniqueConstraint(
                fields=["tenant_id", "offering_id", "staff_master_uuid"],
                name=ENROLLMENT_CONSTRAINT,
            ),
        )

    names = _constraints(schema_editor, Fact._meta.db_table)
    if FACT_UUID_INDEX not in names:
        schema_editor.add_index(
            Fact,
            models.Index(
                fields=["staff_master_uuid", "fact_type", "valid_from"],
                name=FACT_UUID_INDEX,
            ),
        )

    for model_name, constraint_name in IDENTITY_CHECKS:
        Model = apps.get_model("hr10_development", model_name)
        names = _constraints(schema_editor, Model._meta.db_table)
        if constraint_name not in names:
            schema_editor.add_constraint(Model, _identity_check(constraint_name))


def remove_identity_guards(apps, schema_editor):
    Enrollment = apps.get_model("hr10_development", "HrLearningEnrollment")
    Fact = apps.get_model("hr10_development", "HrDevelopmentFact")

    for model_name, constraint_name in reversed(IDENTITY_CHECKS):
        Model = apps.get_model("hr10_development", model_name)
        names = _constraints(schema_editor, Model._meta.db_table)
        if constraint_name in names:
            schema_editor.remove_constraint(Model, _identity_check(constraint_name))

    names = _constraints(schema_editor, Enrollment._meta.db_table)
    if ENROLLMENT_CONSTRAINT in names:
        schema_editor.remove_constraint(
            Enrollment,
            models.UniqueConstraint(
                fields=["tenant_id", "offering_id", "staff_master_uuid"],
                name=ENROLLMENT_CONSTRAINT,
            ),
        )

    names = _constraints(schema_editor, Fact._meta.db_table)
    if FACT_UUID_INDEX in names:
        schema_editor.remove_index(
            Fact,
            models.Index(
                fields=["staff_master_uuid", "fact_type", "valid_from"],
                name=FACT_UUID_INDEX,
            ),
        )


def install_dual_identity_fact_parent_trigger(apps, schema_editor):
    if schema_editor.connection.vendor != "mysql":
        return
    schema_editor.execute("DROP TRIGGER IF EXISTS hr10_development_fact_tenant_parent")
    schema_editor.execute(
        """
        CREATE TRIGGER hr10_development_fact_tenant_parent
        BEFORE INSERT ON hr_development_fact
        FOR EACH ROW
        BEGIN
            IF NEW.supersedes_fact_id IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM hr_development_fact parent
                WHERE parent.id = NEW.supersedes_fact_id
                  AND parent.tenant_id = NEW.tenant_id
                  AND (
                    (
                      parent.staff_master_uuid IS NOT NULL
                      AND NEW.staff_master_uuid IS NOT NULL
                      AND parent.staff_master_uuid = NEW.staff_master_uuid
                    )
                    OR (
                      (parent.staff_master_uuid IS NULL OR NEW.staff_master_uuid IS NULL)
                      AND parent.staff_master_id IS NOT NULL
                      AND NEW.staff_master_id IS NOT NULL
                      AND parent.staff_master_id = NEW.staff_master_id
                    )
                  )
            ) THEN
                SIGNAL SQLSTATE '45000'
                SET MESSAGE_TEXT = 'HR10_DEVELOPMENT_FACT_PARENT_NOT_IN_TENANT';
            END IF;
        END
        """
    )


def restore_legacy_fact_parent_trigger(apps, schema_editor):
    if schema_editor.connection.vendor != "mysql":
        return
    schema_editor.execute("DROP TRIGGER IF EXISTS hr10_development_fact_tenant_parent")
    schema_editor.execute(
        """
        CREATE TRIGGER hr10_development_fact_tenant_parent
        BEFORE INSERT ON hr_development_fact
        FOR EACH ROW
        BEGIN
            IF NEW.supersedes_fact_id IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM hr_development_fact parent
                WHERE parent.id = NEW.supersedes_fact_id
                  AND parent.tenant_id = NEW.tenant_id
                  AND parent.staff_master_id = NEW.staff_master_id
            ) THEN
                SIGNAL SQLSTATE '45000'
                SET MESSAGE_TEXT = 'HR10_DEVELOPMENT_FACT_PARENT_NOT_IN_TENANT';
            END IF;
        END
        """
    )


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("hr10_development", "0027_backfill_hr10_staff_uuid"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(add_identity_guards, remove_identity_guards),
            ],
            state_operations=[
                migrations.AddConstraint(
                    model_name="hrlearningenrollment",
                    constraint=models.UniqueConstraint(
                        fields=("tenant_id", "offering_id", "staff_master_uuid"),
                        name=ENROLLMENT_CONSTRAINT,
                    ),
                ),
                migrations.AddIndex(
                    model_name="hrdevelopmentfact",
                    index=models.Index(
                        fields=["staff_master_uuid", "fact_type", "valid_from"],
                        name=FACT_UUID_INDEX,
                    ),
                ),
                migrations.AddConstraint(
                    model_name="hrtrainingrequest",
                    constraint=_identity_check("ck_hr10_request_staff_identity"),
                ),
                migrations.AddConstraint(
                    model_name="hrlearningenrollment",
                    constraint=_identity_check("ck_hr10_enroll_staff_identity"),
                ),
                migrations.AddConstraint(
                    model_name="hrfurtherstudycase",
                    constraint=_identity_check("ck_hr10_study_staff_identity"),
                ),
                migrations.AddConstraint(
                    model_name="hrenterprisepracticeassignment",
                    constraint=_identity_check("ck_hr10_practice_staff_identity"),
                ),
                migrations.AddConstraint(
                    model_name="hrdevelopmentoutput",
                    constraint=_identity_check("ck_hr10_output_staff_identity"),
                ),
                migrations.AddConstraint(
                    model_name="hrdevelopmentfact",
                    constraint=_identity_check("ck_hr10_fact_staff_identity"),
                ),
                migrations.AddConstraint(
                    model_name="hrdevelopmentmetricledger",
                    constraint=_identity_check("ck_hr10_metric_staff_identity"),
                ),
            ],
        ),
        migrations.RunPython(
            install_dual_identity_fact_parent_trigger,
            restore_legacy_fact_parent_trigger,
        ),
    ]
