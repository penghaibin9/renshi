import uuid

from django.test import TestCase

from hr_title.models import TitleApplicationCase, TitleMaterialSnapshot
from hr_title.services.material_service import (
    TitleMaterialError,
    TitleMaterialInput,
    TitleMaterialService,
)


class TitleMaterialServiceTests(TestCase):
    def setUp(self):
        self.case = TitleApplicationCase.objects.create(
            tenant_id=77,
            case_no="TITLE-2026-001",
            person_id=uuid.uuid4(),
            policy_version_id=uuid.uuid4(),
            batch_no="BATCH-2026",
            requested_title_code="ASSOCIATE_PROFESSOR",
            status=TitleApplicationCase.Status.SUBMITTED,
        )
        self.payload = TitleMaterialInput(
            material_no="MAT-001",
            application_case_id=self.case.id,
            material_type="REPRESENTATIVE_ACHIEVEMENT",
            display_name="代表性成果一",
            content_hash="a" * 64,
            source_domain="HR10",
            source_ref="development-fact-001",
            source_version="v3",
            snapshot_json={"name": "代表性成果一", "score": "verified"},
        )

    def test_attach_is_tenant_scoped_and_idempotent(self):
        service = TitleMaterialService(77, actor_user_id=9)

        first = service.attach_snapshot(self.payload)
        second = service.attach_snapshot(self.payload)

        self.assertEqual(first.id, second.id)
        self.assertEqual(TitleMaterialSnapshot.objects.filter(tenant_id=77).count(), 1)
        self.assertEqual(first.source_domain, "HR10")
        self.assertEqual(first.status, TitleMaterialSnapshot.Status.ATTACHED)

    def test_cross_tenant_case_fails_closed(self):
        with self.assertRaises(TitleMaterialError) as cm:
            TitleMaterialService(88).attach_snapshot(self.payload)

        self.assertEqual(cm.exception.code, "TITLE_CASE_NOT_FOUND")
        self.assertFalse(TitleMaterialSnapshot.objects.filter(tenant_id=88).exists())

    def test_same_material_no_with_different_payload_conflicts(self):
        service = TitleMaterialService(77)
        service.attach_snapshot(self.payload)
        changed = TitleMaterialInput(
            **{
                **self.payload.__dict__,
                "display_name": "被替换的不同材料",
            }
        )

        with self.assertRaises(TitleMaterialError) as cm:
            service.attach_snapshot(changed)

        self.assertEqual(cm.exception.code, "TITLE_MATERIAL_IDEMPOTENCY_CONFLICT")

    def test_accepted_material_cannot_be_edited_in_place(self):
        service = TitleMaterialService(77)
        material = service.attach_snapshot(self.payload)
        material = service.accept(material.id)
        material.display_name = "试图覆盖历史证据"

        with self.assertRaises(ValueError) as cm:
            material.save()

        self.assertIn("TITLE_MATERIAL_SNAPSHOT_IMMUTABLE", str(cm.exception))

    def test_returned_material_is_replaced_by_new_snapshot(self):
        service = TitleMaterialService(77)
        original = service.attach_snapshot(self.payload)
        original = service.return_for_correction(original.id)
        replacement = service.attach_snapshot(
            TitleMaterialInput(
                material_no="MAT-002",
                application_case_id=self.case.id,
                material_type="REPRESENTATIVE_ACHIEVEMENT",
                display_name="代表性成果一（补正）",
                content_hash="b" * 64,
                source_domain="HR10",
                source_ref="development-fact-001",
                source_version="v4",
                snapshot_json={"name": "代表性成果一（补正）"},
                supersedes_snapshot_id=original.id,
            )
        )

        self.assertEqual(original.status, TitleMaterialSnapshot.Status.RETURNED)
        self.assertEqual(replacement.supersedes_snapshot_id, original.id)
        self.assertNotEqual(replacement.id, original.id)

    def test_review_started_blocks_new_material(self):
        self.case.status = TitleApplicationCase.Status.UNDER_REVIEW
        self.case.save(update_fields=["status", "updated_at"])

        with self.assertRaises(TitleMaterialError) as cm:
            TitleMaterialService(77).attach_snapshot(self.payload)

        self.assertEqual(cm.exception.code, "TITLE_MATERIAL_CASE_NOT_ATTACHABLE")
