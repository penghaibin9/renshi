import uuid
from datetime import date

from django.test import TestCase

from hr_exit.models import ExitCase, ExitHandoverItem
from hr_exit.services.case_service import ExitCaseError, ExitCaseService
from hr_exit.services.handover_service import (
    ExitHandoverError,
    ExitHandoverService,
)


class Hr16HandoverServiceTests(TestCase):
    def _case(self, *, tenant_id=7, status=ExitCase.Status.HANDOVER):
        return ExitCase.objects.create(
            tenant_id=tenant_id,
            case_no=f"EXIT-{tenant_id}-{uuid.uuid4().hex[:8]}",
            person_id=uuid.uuid4(),
            employment_relationship_id=uuid.uuid4(),
            exit_type=ExitCase.ExitType.RESIGNATION,
            status=status,
            requested_date=date(2026, 8, 1),
            last_working_date=date(2026, 8, 31),
            planned_employment_end_date=date(2026, 9, 1),
        )

    def test_settlement_fails_closed_when_required_checklist_not_configured(self):
        case = self._case()

        with self.assertRaises(ExitCaseError) as ctx:
            ExitCaseService(7).begin_settlement(case.id)

        self.assertEqual(ctx.exception.code, "EXIT_HANDOVER_CHECKLIST_REQUIRED")
        case.refresh_from_db()
        self.assertEqual(case.status, ExitCase.Status.HANDOVER)

    def test_pending_required_item_blocks_settlement(self):
        case = self._case()
        ExitHandoverService(7).add_item(
            case_id=case.id,
            item_no="HO-001",
            category_code="WORK",
            title="工作资料移交",
            required=True,
        )

        with self.assertRaises(ExitCaseError) as ctx:
            ExitCaseService(7).begin_settlement(case.id)

        self.assertEqual(ctx.exception.code, "EXIT_HANDOVER_INCOMPLETE")
        case.refresh_from_db()
        self.assertEqual(case.status, ExitCase.Status.HANDOVER)

    def test_completed_and_waived_required_items_allow_settlement(self):
        case = self._case()
        service = ExitHandoverService(7, actor_user_id=88)
        completed = service.add_item(
            case_id=case.id,
            item_no="HO-002",
            category_code="WORK",
            title="工作资料移交",
        )
        waived = service.add_item(
            case_id=case.id,
            item_no="HO-003",
            category_code="ASSET",
            title="无领用资产确认",
        )
        service.complete(completed.id, evidence_ref="file:handover-2026-001")
        service.waive(waived.id, reason="资产系统确认无在用资产")

        gate = service.gate(case.id)
        self.assertTrue(gate.ready)
        self.assertEqual(gate.configured_required, 2)
        self.assertEqual(gate.completed_required, 1)
        self.assertEqual(gate.waived_required, 1)
        self.assertEqual(gate.pending_required, 0)

        ExitCaseService(7, actor_user_id=88).begin_settlement(case.id)
        case.refresh_from_db()
        self.assertEqual(case.status, ExitCase.Status.SETTLEMENT)

    def test_optional_pending_item_does_not_block_required_gate(self):
        case = self._case()
        service = ExitHandoverService(7)
        required = service.add_item(
            case_id=case.id,
            item_no="HO-004",
            category_code="WORK",
            title="核心工作交接",
            required=True,
        )
        service.add_item(
            case_id=case.id,
            item_no="HO-005",
            category_code="OTHER",
            title="可选说明",
            required=False,
        )
        service.complete(required.id)

        gate = service.assert_ready_for_settlement(case.id)
        self.assertTrue(gate.ready)

    def test_waive_requires_reason(self):
        case = self._case()
        item = ExitHandoverService(7).add_item(
            case_id=case.id,
            item_no="HO-006",
            category_code="WORK",
            title="工作资料移交",
        )

        with self.assertRaises(ExitHandoverError) as ctx:
            ExitHandoverService(7).waive(item.id, reason="")

        self.assertEqual(ctx.exception.code, "EXIT_HANDOVER_WAIVER_REASON_REQUIRED")
        item.refresh_from_db()
        self.assertEqual(item.status, ExitHandoverItem.Status.PENDING)

    def test_cross_tenant_item_access_fails_closed(self):
        case = self._case(tenant_id=8)
        item = ExitHandoverService(8).add_item(
            case_id=case.id,
            item_no="HO-007",
            category_code="WORK",
            title="工作资料移交",
        )

        with self.assertRaises(ExitHandoverError) as ctx:
            ExitHandoverService(7).complete(item.id)

        self.assertEqual(ctx.exception.code, "EXIT_HANDOVER_ITEM_NOT_FOUND")

    def test_terminal_item_is_immutable_and_correction_must_supersede(self):
        case = self._case()
        service = ExitHandoverService(7)
        item = service.add_item(
            case_id=case.id,
            item_no="HO-008",
            category_code="WORK",
            title="工作资料移交",
        )
        service.complete(item.id)
        item.title = "偷偷改标题"
        with self.assertRaisesRegex(ValueError, "EXIT_HANDOVER_ITEM_IMMUTABLE"):
            item.save(update_fields=["title", "updated_at"])

        replacement = service.add_item(
            case_id=case.id,
            item_no="HO-009",
            category_code="WORK",
            title="工作资料移交（修正版）",
            supersedes_item_id=item.id,
        )
        self.assertEqual(replacement.supersedes_item_id, item.id)
        self.assertEqual(replacement.status, ExitHandoverItem.Status.PENDING)
