import hashlib
import json

from django.db import migrations, models


def _hash_result(row):
    payload = {
        "tenantId": int(row.tenant_id),
        "resultNo": row.result_no,
        "personId": str(row.person_id),
        "applicationCaseId": str(row.application_case_id),
        "titleCode": row.title_code,
        "titleName": row.title_name,
        "titleSeriesCode": row.title_series_code,
        "titleLevelCode": row.title_level_code,
        "effectiveFrom": row.effective_from.isoformat(),
        "effectiveTo": row.effective_to.isoformat() if row.effective_to else None,
        "status": row.status,
        "supersedesResultId": (
            str(row.supersedes_result_id) if row.supersedes_result_id else None
        ),
        "sealedAt": row.sealed_at.isoformat(),
        "createdBy": row.created_by,
        "updatedBy": row.updated_by,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def seal_existing_results_and_permissions(apps, schema_editor):
    Result = apps.get_model("hr_title", "ProfessionalTitleResult")
    ContentType = apps.get_model("contenttypes", "ContentType")
    Permission = apps.get_model("auth", "Permission")

    pending = []
    for row in Result.objects.all().iterator(chunk_size=500):
        row.sealed_at = row.created_at
        row.content_hash = _hash_result(row)
        pending.append(row)
        if len(pending) == 500:
            Result.objects.bulk_update(pending, ["sealed_at", "content_hash"])
            pending = []
    if pending:
        Result.objects.bulk_update(pending, ["sealed_at", "content_hash"])

    content_type, _created = ContentType.objects.get_or_create(
        app_label="hr_title",
        model="titleapplicationcase",
    )
    Permission.objects.update_or_create(
        content_type=content_type,
        codename="hr.title.result",
        defaults={"name": "发布 HR13 正式职称结果"},
    )
    Permission.objects.get_or_create(
        content_type=content_type,
        codename="hr.title.result.correct",
        defaults={"name": "修订与撤销 HR13 已封板正式职称结果"},
    )


def reverse_permissions(apps, schema_editor):
    Permission = apps.get_model("auth", "Permission")
    Permission.objects.filter(
        content_type__app_label="hr_title",
        content_type__model="titleapplicationcase",
        codename="hr.title.result.correct",
    ).delete()
    Permission.objects.filter(
        content_type__app_label="hr_title",
        content_type__model="titleapplicationcase",
        codename="hr.title.result",
    ).update(name="发布、修订与撤销 HR13 正式职称结果")


def install_mysql_write_seal(apps, schema_editor):
    if schema_editor.connection.vendor != "mysql":
        return
    schema_editor.execute("DROP TRIGGER IF EXISTS hr13_title_result_no_update")
    schema_editor.execute("DROP TRIGGER IF EXISTS hr13_title_result_no_delete")
    schema_editor.execute(
        """
        CREATE TRIGGER hr13_title_result_no_update
        BEFORE UPDATE ON hr13_professional_title_result
        FOR EACH ROW
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'TITLE_RESULT_IMMUTABLE: append a successor fact'
        """
    )
    schema_editor.execute(
        """
        CREATE TRIGGER hr13_title_result_no_delete
        BEFORE DELETE ON hr13_professional_title_result
        FOR EACH ROW
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'TITLE_RESULT_IMMUTABLE: formal facts cannot be deleted'
        """
    )


def remove_mysql_write_seal(apps, schema_editor):
    if schema_editor.connection.vendor != "mysql":
        return
    schema_editor.execute("DROP TRIGGER IF EXISTS hr13_title_result_no_update")
    schema_editor.execute("DROP TRIGGER IF EXISTS hr13_title_result_no_delete")


class Migration(migrations.Migration):
    # MySQL 8.4 trigger DDL commits implicitly and cannot run in an atomic
    # migration block. Data/schema operations remain ordered by Django.
    atomic = False

    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
        ("contenttypes", "0002_remove_content_type_name"),
        ("hr_title", "0007_title_result_permission"),
    ]

    operations = [
        migrations.AddField(
            model_name="professionaltitleresult",
            name="content_hash",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddField(
            model_name="professionaltitleresult",
            name="sealed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RunPython(
            seal_existing_results_and_permissions,
            reverse_permissions,
        ),
        migrations.AddConstraint(
            model_name="professionaltitleresult",
            constraint=models.CheckConstraint(
                condition=models.Q(content_hash__regex=r"^[0-9a-f]{64}$"),
                name="ck_hr13_result_hash_format",
            ),
        ),
        migrations.AddConstraint(
            model_name="professionaltitleresult",
            constraint=models.CheckConstraint(
                condition=models.Q(sealed_at__isnull=False),
                name="ck_hr13_result_sealed_at",
            ),
        ),
        migrations.RunPython(install_mysql_write_seal, remove_mysql_write_seal),
    ]
