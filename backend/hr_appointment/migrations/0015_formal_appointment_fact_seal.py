import hashlib
import json

import hr_appointment.models
from django.db import migrations, models


HASH_FIELDS = (
    "id",
    "tenant_id",
    "appointment_no",
    "person_id",
    "position_instance_id",
    "application_case_id",
    "reservation_id",
    "level_code",
    "effective_from",
    "effective_to",
    "status",
    "effect_receipt_json",
    "supersedes_fact_id",
    "fact_kind",
    "revision_reason",
    "authority_receipt_json",
    "idempotency_key",
    "sealed_at",
    "published_by",
)


def _hash(fact):
    body = {}
    for field in HASH_FIELDS:
        value = getattr(fact, field)
        if hasattr(value, "isoformat"):
            value = value.isoformat()
        body[field] = value
    encoded = json.dumps(
        body,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def seal_legacy_facts(apps, schema_editor):
    Fact = apps.get_model("hr_appointment", "PositionAppointmentFact")
    alias = schema_editor.connection.alias
    for fact in Fact.objects.using(alias).all().iterator():
        if not fact.idempotency_key:
            fact.idempotency_key = f"legacy:{fact.id}"
        if fact.supersedes_fact_id:
            fact.fact_kind = "TERM_SUCCESSOR"
        if fact.status != "EFFECT_PENDING":
            fact.sealed_at = fact.updated_at or fact.created_at
            fact.published_by = fact.updated_by or fact.created_by or 1
            fact.authority_receipt_json = {
                "permissionCode": (
                    "hr.appointment.term"
                    if fact.supersedes_fact_id
                    else "hr.appointment.fact.publish"
                ),
                "authorityRef": "LEGACY-MIGRATION-0015",
                "actorUserId": fact.published_by,
                "evidence": {"migration": "0015_formal_appointment_fact_seal"},
            }
            fact.content_hash = _hash(fact)
        fact.save(
            using=alias,
            update_fields=[
                "fact_kind",
                "idempotency_key",
                "sealed_at",
                "published_by",
                "authority_receipt_json",
                "content_hash",
            ],
        )


def create_mysql_seal_triggers(apps, schema_editor):
    if schema_editor.connection.vendor != "mysql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("DROP TRIGGER IF EXISTS hr14_fact_reject_sealed_update")
        cursor.execute("DROP TRIGGER IF EXISTS hr14_fact_reject_sealed_delete")
    statements = (
        """
        CREATE TRIGGER hr14_fact_reject_sealed_update
        BEFORE UPDATE ON hr14_position_appointment_fact
        FOR EACH ROW
        BEGIN
            IF OLD.sealed_at IS NOT NULL THEN
                SIGNAL SQLSTATE '45000'
                    SET MESSAGE_TEXT = 'HR14_APPOINTMENT_FACT_APPEND_ONLY_UPDATE';
            END IF;
        END
        """,
        """
        CREATE TRIGGER hr14_fact_reject_sealed_delete
        BEFORE DELETE ON hr14_position_appointment_fact
        FOR EACH ROW
        BEGIN
            IF OLD.sealed_at IS NOT NULL THEN
                SIGNAL SQLSTATE '45000'
                    SET MESSAGE_TEXT = 'HR14_APPOINTMENT_FACT_APPEND_ONLY_DELETE';
            END IF;
        END
        """,
    )
    with schema_editor.connection.cursor() as cursor:
        for statement in statements:
            cursor.execute(statement)


def drop_mysql_seal_triggers(apps, schema_editor):
    if schema_editor.connection.vendor != "mysql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("DROP TRIGGER IF EXISTS hr14_fact_reject_sealed_update")
        cursor.execute("DROP TRIGGER IF EXISTS hr14_fact_reject_sealed_delete")


class Migration(migrations.Migration):
    # MySQL trigger DDL performs implicit commits; keep this migration outside
    # Django's atomic wrapper so forward and reverse execution are legal.
    atomic = False

    dependencies = [("hr_appointment", "0014_collective_decision_authority")]

    operations = [
        migrations.AlterModelOptions(
            name="appointmentpolicyversion",
            options={
                "permissions": [
                    ("hr.appointment.view", "查看 HR14 岗位聘任工作区"),
                    ("hr.appointment.review", "执行 HR14 评议排序"),
                    ("hr.appointment.publicity", "维护 HR14 拟聘公示与异议"),
                    ("hr.appointment.effect", "执行 HR14 正式聘任生效"),
                    ("hr.appointment.fact.publish", "首次发布 HR14 正式任命事实"),
                    ("hr.appointment.fact.correct", "追加 HR14 正式任命更正事实"),
                    ("hr.appointment.fact.revoke", "追加 HR14 正式任命撤销事实"),
                ]
            },
        ),
        migrations.AddField(
            model_name="positionappointmentfact",
            name="authority_receipt_json",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="positionappointmentfact",
            name="content_hash",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddField(
            model_name="positionappointmentfact",
            name="fact_kind",
            field=models.CharField(
                choices=[
                    ("INITIAL", "Initial formal appointment"),
                    ("TERM_SUCCESSOR", "Term-governance successor"),
                    ("CORRECTION", "Authorized correction"),
                    ("REVOCATION", "Authorized revocation"),
                    ("EXIT_CLOSURE", "Exit closure"),
                ],
                db_index=True,
                default="INITIAL",
                max_length=24,
            ),
        ),
        migrations.AddField(
            model_name="positionappointmentfact",
            name="idempotency_key",
            field=models.CharField(default="", max_length=128),
        ),
        migrations.AddField(
            model_name="positionappointmentfact",
            name="published_by",
            field=models.PositiveBigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="positionappointmentfact",
            name="revision_reason",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="positionappointmentfact",
            name="sealed_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.RunPython(seal_legacy_facts, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="positionappointmentfact",
            name="idempotency_key",
            field=models.CharField(
                default=hr_appointment.models._appointment_fact_idempotency_key,
                max_length=128,
            ),
        ),
        migrations.AddConstraint(
            model_name="positionappointmentfact",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(
                        ("content_hash", ""),
                        ("sealed_at__isnull", True),
                        ("status", "EFFECT_PENDING"),
                    ),
                    models.Q(
                        models.Q(("status", "EFFECT_PENDING"), _negated=True),
                        ("sealed_at__isnull", False),
                        models.Q(("content_hash", ""), _negated=True),
                        ("published_by__isnull", False),
                    ),
                    _connector="OR",
                ),
                name="ck_hr14_fact_seal_state",
            ),
        ),
        migrations.AddConstraint(
            model_name="positionappointmentfact",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(("fact_kind", "INITIAL"), ("supersedes_fact_id__isnull", True)),
                    models.Q(
                        models.Q(("fact_kind", "INITIAL"), _negated=True),
                        ("supersedes_fact_id__isnull", False),
                    ),
                    _connector="OR",
                ),
                name="ck_hr14_fact_lineage_kind",
            ),
        ),
        migrations.AddConstraint(
            model_name="positionappointmentfact",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("supersedes_fact_id__isnull", True),
                    models.Q(("supersedes_fact_id", models.F("id")), _negated=True),
                    _connector="OR",
                ),
                name="ck_hr14_fact_not_self_parent",
            ),
        ),
        migrations.AddConstraint(
            model_name="positionappointmentfact",
            constraint=models.UniqueConstraint(
                fields=("tenant_id", "supersedes_fact_id"),
                name="uq_hr14_fact_one_successor",
            ),
        ),
        migrations.AddConstraint(
            model_name="positionappointmentfact",
            constraint=models.UniqueConstraint(
                fields=("tenant_id", "idempotency_key"),
                name="uq_hr14_fact_idempotency",
            ),
        ),
        migrations.RunPython(create_mysql_seal_triggers, drop_mysql_seal_triggers),
    ]
