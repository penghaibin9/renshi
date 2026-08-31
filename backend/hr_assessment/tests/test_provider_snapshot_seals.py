import uuid
import json

from django.db import DatabaseError, connection, transaction
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from hr_assessment.models.provider_snapshot import (
    HrProviderSnapshotItem,
    HrProviderSnapshotSet,
)


class ProviderSnapshotOrmSealTests(TestCase):
    def setUp(self):
        self.case_id = uuid.uuid4()
        self.snapshot_set = HrProviderSnapshotSet.objects.create(
            tenant_id=77,
            case_id=self.case_id,
            as_of=timezone.now(),
            authority_json={"policyVersionId": str(uuid.uuid4())},
            required_providers_json=["person"],
            provider_status_json={"person": {"status": "OK"}},
            content_hash="a" * 64,
            status="CAPTURING",
            captured_at=None,
        )
        self.item = HrProviderSnapshotItem.objects.create(
            tenant_id=77,
            snapshot_set=self.snapshot_set,
            case_id=self.case_id,
            provider_type="person",
            source_object_type="HrStaffEvidence",
            source_object_id=str(uuid.uuid4()),
            source_version="hr03-v1",
            source_as_of=timezone.now(),
            trust_level="SOURCE_VERIFIED",
            snapshot_hash="",
            snapshot_json={"staffId": str(uuid.uuid4()), "active": True},
            status="VERIFIED",
        )
        self.snapshot_set.seal_capture(status="READY")

    def test_item_hash_is_server_calculated(self):
        self.assertEqual(self.item.snapshot_hash, self.item.calculate_snapshot_hash())

    def test_snapshot_rows_are_append_only_through_orm(self):
        with self.assertRaisesRegex(ValueError, "HR12_PROVIDER_SNAPSHOT_IMMUTABLE"):
            HrProviderSnapshotSet.objects.filter(id=self.snapshot_set.id).update(
                status="BLOCKED"
            )
        with self.assertRaisesRegex(ValueError, "HR12_PROVIDER_SNAPSHOT_IMMUTABLE"):
            HrProviderSnapshotItem.objects.filter(id=self.item.id).delete()
        with self.assertRaisesRegex(ValueError, "HR12_PROVIDER_SNAPSHOT_ITEM_IMMUTABLE"):
            self.item.save()
        with self.assertRaisesRegex(
            ValueError, "HR12_PROVIDER_SNAPSHOT_MEMBERSHIP_SEALED"
        ):
            HrProviderSnapshotItem.objects.create(
                tenant_id=77,
                snapshot_set=self.snapshot_set,
                case_id=self.case_id,
                provider_type="person",
                source_object_type="HrStaffEvidence",
                source_object_id="late-row",
                snapshot_json={"late": True},
                status="VERIFIED",
            )

    def test_hash_and_parent_scope_mismatch_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "HR12_PROVIDER_SNAPSHOT_HASH_MISMATCH"):
            HrProviderSnapshotItem.objects.create(
                tenant_id=77,
                snapshot_set=self.snapshot_set,
                case_id=self.case_id,
                provider_type="person",
                source_object_type="HrStaffEvidence",
                source_object_id="bad-hash",
                snapshot_hash="b" * 64,
                snapshot_json={"different": True},
                status="VERIFIED",
            )
        with self.assertRaisesRegex(ValueError, "HR12_PROVIDER_SNAPSHOT_SCOPE_MISMATCH"):
            HrProviderSnapshotItem.objects.create(
                tenant_id=88,
                snapshot_set=self.snapshot_set,
                case_id=self.case_id,
                provider_type="person",
                source_object_type="HrStaffEvidence",
                source_object_id="cross-tenant",
                snapshot_hash="",
                snapshot_json={"staffId": "cross-tenant"},
                status="VERIFIED",
            )

    def test_mysql_trigger_blocks_raw_snapshot_update(self):
        if connection.vendor != "mysql":
            self.skipTest("MySQL trigger assertion")
        with self.assertRaises(DatabaseError), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE hr_assessment_provider_snapshot_item "
                    "SET status = %s WHERE id = %s",
                    ["CONFLICT", self.item.id.hex],
                )
        with self.assertRaises(DatabaseError), transaction.atomic():
            now = timezone.now()
            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO hr_assessment_provider_snapshot_item "
                    "(id, tenant_id, created_at, updated_at, snapshot_set_id, "
                    "case_id, provider_type, source_object_type, source_object_id, "
                    "source_version, source_as_of, trust_level, snapshot_hash, "
                    "snapshot_json, status, error_message) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
                    "%s, %s, %s, %s, %s)",
                    [
                        uuid.uuid4().hex,
                        77,
                        now,
                        now,
                        self.snapshot_set.id.hex,
                        self.case_id.hex,
                        "person",
                        "HrStaffEvidence",
                        "raw-late-row",
                        "hr03-v1",
                        now,
                        "SOURCE_VERIFIED",
                        "a" * 64,
                        json.dumps({"late": True}),
                        "VERIFIED",
                        "",
                    ],
                )


class ProviderSnapshotMigrationContractTests(SimpleTestCase):
    def test_trigger_migration_is_non_atomic_and_covers_both_snapshot_tables(self):
        from importlib import import_module

        migration = import_module(
            "hr_assessment.migrations.0014_provider_snapshot_seals"
        )
        self.assertFalse(migration.Migration.atomic)
        self.assertEqual(
            set(migration.TABLES),
            {
                "hr_assessment_provider_snapshot_set",
                "hr_assessment_provider_snapshot_item",
            },
        )
