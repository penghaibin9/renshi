from django.db import migrations, models


def backfill_assignment_case(apps, schema_editor):
    Assignment = apps.get_model("hr_title", "TitleReviewAssignment")
    ReviewRound = apps.get_model("hr_title", "TitleReviewRound")
    alias = schema_editor.connection.alias
    rounds = {
        (row.tenant_id, row.id): row.application_case_id
        for row in ReviewRound.objects.using(alias).only(
            "id", "tenant_id", "application_case_id"
        )
    }
    for assignment in Assignment.objects.using(alias).only(
        "id", "tenant_id", "review_round_id"
    ).iterator(chunk_size=500):
        case_id = rounds.get((assignment.tenant_id, assignment.review_round_id))
        if case_id is None:
            raise RuntimeError(
                "TITLE_REVIEW_PANEL_EVIDENCE_INCONSISTENT: assignment has no tenant-matched round"
            )
        Assignment.objects.using(alias).filter(pk=assignment.pk).update(
            application_case_id=case_id
        )


def install_mysql_assignment_seal(apps, schema_editor):
    if schema_editor.connection.vendor != "mysql":
        return
    schema_editor.execute("DROP TRIGGER IF EXISTS hr13_assignment_no_update")
    schema_editor.execute("DROP TRIGGER IF EXISTS hr13_assignment_no_delete")
    schema_editor.execute(
        """
        CREATE TRIGGER hr13_assignment_no_update
        BEFORE UPDATE ON hr13_title_review_assignment
        FOR EACH ROW
        BEGIN
            IF NOT (
                OLD.tenant_id <=> NEW.tenant_id
                AND OLD.assignment_no <=> NEW.assignment_no
                AND OLD.application_case_id <=> NEW.application_case_id
                AND OLD.review_round_id <=> NEW.review_round_id
                AND OLD.reviewer_staff_id <=> NEW.reviewer_staff_id
                AND OLD.reviewer_role <=> NEW.reviewer_role
                AND OLD.assigned_by <=> NEW.assigned_by
                AND OLD.supersedes_assignment_id <=> NEW.supersedes_assignment_id
                AND OLD.replacement_reason_code <=> NEW.replacement_reason_code
                AND OLD.replacement_reason <=> NEW.replacement_reason
                AND OLD.replacement_authorized_by <=> NEW.replacement_authorized_by
                AND OLD.replacement_at <=> NEW.replacement_at
            ) THEN
                SIGNAL SQLSTATE '45000'
                SET MESSAGE_TEXT = 'TITLE_REVIEW_ASSIGNMENT_IDENTITY_IMMUTABLE';
            END IF;
            IF (
                OLD.responded_at IS NOT NULL
                OR EXISTS (
                    SELECT 1 FROM hr13_title_review_ballot b
                    WHERE b.tenant_id = OLD.tenant_id AND b.assignment_id = OLD.id
                )
            ) AND NOT (
                OLD.status <=> NEW.status
                AND OLD.conflict_declared <=> NEW.conflict_declared
                AND OLD.conflict_note <=> NEW.conflict_note
                AND OLD.responded_at <=> NEW.responded_at
            ) THEN
                SIGNAL SQLSTATE '45000'
                SET MESSAGE_TEXT = 'TITLE_REVIEW_ASSIGNMENT_FACT_IMMUTABLE';
            END IF;
        END
        """
    )
    schema_editor.execute(
        """
        CREATE TRIGGER hr13_assignment_no_delete
        BEFORE DELETE ON hr13_title_review_assignment
        FOR EACH ROW
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'TITLE_REVIEW_ASSIGNMENT_APPEND_ONLY'
        """
    )


def remove_mysql_assignment_seal(apps, schema_editor):
    if schema_editor.connection.vendor != "mysql":
        return
    schema_editor.execute("DROP TRIGGER IF EXISTS hr13_assignment_no_update")
    schema_editor.execute("DROP TRIGGER IF EXISTS hr13_assignment_no_delete")


class Migration(migrations.Migration):
    dependencies = [("hr_title", "0008_title_result_integrity")]

    operations = [
        migrations.AlterModelOptions(
            name="titlepolicyversion",
            options={
                "permissions": [
                    ("hr.title.view", "查看 HR13 职称评审工作区"),
                    ("hr.title.review", "执行 HR13 资格审查"),
                    ("hr.title.panel", "维护 HR13 专家评议与表决"),
                    ("hr.title.panel.correct", "追加更正 HR13 已产生事实的评委分配"),
                    ("hr.title.publicity", "维护 HR13 公示与异议复核"),
                ]
            },
        ),
        migrations.AddField(
            model_name="titlereviewassignment",
            name="application_case_id",
            field=models.UUIDField(db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="titlereviewassignment",
            name="replacement_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="titlereviewassignment",
            name="replacement_authorized_by",
            field=models.PositiveBigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="titlereviewassignment",
            name="replacement_reason",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="titlereviewassignment",
            name="replacement_reason_code",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddField(
            model_name="titlereviewassignment",
            name="supersedes_assignment_id",
            field=models.UUIDField(blank=True, null=True),
        ),
        migrations.RunPython(backfill_assignment_case, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="titlereviewassignment",
            name="application_case_id",
            field=models.UUIDField(db_index=True),
        ),
        migrations.AddConstraint(
            model_name="titlereviewassignment",
            constraint=models.UniqueConstraint(
                fields=("tenant_id", "supersedes_assignment_id"),
                name="uq_hr13_assignment_supersedes",
            ),
        ),
        migrations.AddConstraint(
            model_name="titlereviewassignment",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(
                        supersedes_assignment_id__isnull=True,
                        replacement_reason_code="",
                        replacement_reason="",
                        replacement_authorized_by__isnull=True,
                        replacement_at__isnull=True,
                    )
                    | (
                        models.Q(supersedes_assignment_id__isnull=False)
                        & ~models.Q(replacement_reason_code="")
                        & ~models.Q(replacement_reason="")
                        & models.Q(replacement_authorized_by__isnull=False)
                        & models.Q(replacement_at__isnull=False)
                    )
                ),
                name="ck_hr13_assignment_lineage",
            ),
        ),
        migrations.AddIndex(
            model_name="titlereviewassignment",
            index=models.Index(
                fields=["tenant_id", "application_case_id", "review_round_id"],
                name="idx_hr13_assignment_case",
            ),
        ),
        migrations.RunPython(
            install_mysql_assignment_seal,
            remove_mysql_assignment_seal,
        ),
    ]
