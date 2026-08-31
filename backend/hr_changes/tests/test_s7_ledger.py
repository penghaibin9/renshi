"""S7 台账/纠错/撤销契约测试。"""

from datetime import date

from django.test import TestCase

from hr_changes.constants import CaseStatus, ChangeActionCode
from hr_changes.models import (
    HrChangeCorrection,
    HrChangeEffectiveSnapshot,
    HrChangeRescind,
    HrPersonnelChangeCase,
)
from hr_changes.selectors.ledger import LedgerSelector
from hr_changes.services.change_service import ChangeService, ChangeServiceError
from hr_changes.services.correction_service import CorrectionService, CorrectionServiceError
from hr_changes.services.rescind_service import RescindService, RescindServiceError
from hr_changes.tests.factories import (
    make_case,
    make_effective_case as make_trusted_effective_case,
    make_org,
    make_position,
)

TENANT = 1


def make_effective_case(**kw):
    return make_trusted_effective_case(TENANT, **kw)


class LedgerSelectorTests(TestCase):
    def test_list_and_filters(self):
        org = make_org(TENANT, "RGXY", "人工智能学院", date(2020, 1, 1))
        c1 = make_effective_case(target_org=org)
        c2 = make_case(TENANT, ChangeActionCode.MANAGER_CHANGE, status=CaseStatus.DRAFT)

        selector = LedgerSelector(TENANT)
        all_items = selector.list()
        self.assertEqual(all_items["total"], 2)

        by_org = selector.list(org_id=org.id)
        self.assertEqual(by_org["total"], 1)
        self.assertEqual(by_org["items"][0]["id"], str(c1.id))

        by_action = selector.list(action_code=ChangeActionCode.MANAGER_CHANGE)
        self.assertEqual(by_action["total"], 1)
        self.assertEqual(by_action["items"][0]["id"], str(c2.id))

        by_status = selector.list(status=CaseStatus.EFFECTIVE)
        self.assertEqual(by_status["total"], 1)

        by_year = selector.list(year=2026)
        self.assertEqual(by_year["total"], 2)

    def test_staff_history(self):
        case = make_effective_case()
        data = LedgerSelector(TENANT).staff_history(case.staff_master_id_id)
        self.assertEqual(data["items"][0]["caseNo"], case.case_no)
        self.assertEqual(data["items"][0]["statusLabel"], "已生效")


class CorrectionServiceTests(TestCase):
    def setUp(self):
        self.case = make_effective_case()
        self.assertIsNotNone(self.case.effective_snapshot)

    def test_full_correction_flow(self):
        svc = CorrectionService(TENANT, actor_user_id=1)
        correction = svc.create_correction(
            case_id=self.case.id,
            correction_type="TARGET_VALUE",
            requested_values={"fields": {"person.preferred_name": "小张"}},
            reason="系统误录",
            authority_version=self.case.staff_master_id.version,
            idempotency_key="s7-create-full",
        )
        self.assertEqual(correction.status, "DRAFT")
        original_snapshot_hash = self.case.effective_snapshot.checksum
        self.assertEqual(correction.previous_snapshot_hash, original_snapshot_hash)

        correction = svc.submit(correction.id)
        correction = svc.approve(correction.id)
        applied = svc.apply(
            correction.id,
            expected_version=correction.version,
            idempotency_key="s7-apply-full",
        )
        self.assertEqual(applied.status, "APPLIED")
        self.assertTrue(applied.new_snapshot_hash)
        self.assertNotEqual(applied.new_snapshot_hash, original_snapshot_hash)
        # 案件转 CORRECTED
        self.case.refresh_from_db()
        self.assertEqual(self.case.status, CaseStatus.CORRECTED)
        self.case.staff_master_id.person_id.refresh_from_db()
        self.assertEqual(self.case.staff_master_id.person_id.preferred_name, "小张")
        self.assertTrue(applied.provider_case_id)

    def test_correction_requires_effective(self):
        draft_case = make_case(TENANT, status=CaseStatus.DRAFT)
        with self.assertRaises(CorrectionServiceError) as cm:
            CorrectionService(TENANT).create_correction(
                case_id=draft_case.id, correction_type="DATE",
                requested_values={"fields": {"person.preferred_name": "x"}}, reason="x",
                authority_version=draft_case.staff_master_id.version,
                idempotency_key="s7-create-draft",
            )
        self.assertEqual(cm.exception.code, "CHANGE_INVALID_STATE")

    def test_apply_requires_approval(self):
        svc = CorrectionService(TENANT, actor_user_id=1)
        correction = svc.create_correction(
            case_id=self.case.id, correction_type="TARGET_VALUE",
            requested_values={"fields": {"person.preferred_name": "X"}}, reason="纠错",
            authority_version=self.case.staff_master_id.version,
            idempotency_key="s7-create-unapproved",
        )
        svc.submit(correction.id)
        with self.assertRaises(CorrectionServiceError) as cm:
            svc.apply(
                correction.id,
                expected_version=2,
                idempotency_key="s7-apply-unapproved",
            )
        self.assertEqual(cm.exception.code, "CHANGE_CORRECTION_REQUIRES_APPROVAL")


class RescindServiceTests(TestCase):
    def test_rescind_without_dependents(self):
        case = make_effective_case()
        svc = RescindService(TENANT, actor_user_id=1)
        rescind = svc.request_rescind(case_id=case.id, reason="政策调整")
        self.assertEqual(rescind.status, "RESCIND_REQUESTED")
        self.assertEqual(rescind.dependent_blockers_json, [])
        svc.approve_rescind(rescind.id)
        executed = svc.execute_rescind(rescind.id)
        self.assertEqual(executed.status, "RESCINDED")
        case.refresh_from_db()
        self.assertEqual(case.status, CaseStatus.RESCINDED)

    def test_rescind_blocked_by_dependent(self):
        case = make_effective_case(requested_effective_at=date(2026, 9, 1))
        # 后续依赖：同人、更晚生效、已生效
        make_effective_case(requested_effective_at=date(2026, 10, 1))
        # 需要把第二个 case 指向同一个人
        from hr_changes.models import HrPersonnelChangeCase

        dependent = HrPersonnelChangeCase.objects.exclude(id=case.id).first()
        dependent.staff_master_id = case.staff_master_id
        dependent.save()
        svc = RescindService(TENANT, actor_user_id=1)
        with self.assertRaises(RescindServiceError) as cm:
            svc.request_rescind(case_id=case.id, reason="撤销")
        self.assertEqual(cm.exception.code, "CHANGE_DEPENDENT_EVENT_EXISTS")

    def test_rescind_only_effective(self):
        draft_case = make_case(TENANT, status=CaseStatus.DRAFT)
        with self.assertRaises(RescindServiceError) as cm:
            RescindService(TENANT).request_rescind(case_id=draft_case.id, reason="x")
        self.assertEqual(cm.exception.code, "CHANGE_ALREADY_EFFECTIVE")


class RescindThroughChangeServiceTests(TestCase):
    def test_rescind_not_delete_transition_recorded(self):
        case = make_effective_case()
        svc = RescindService(TENANT, actor_user_id=1)
        rescind = svc.request_rescind(case_id=case.id, reason="撤销")
        svc.approve_rescind(rescind.id)
        svc.execute_rescind(rescind.id)
        # 案件仍存在（非删除），且流转记录含 rescind
        self.assertTrue(HrPersonnelChangeCase.objects.filter(id=case.id).exists())
        self.assertTrue(case.transitions.filter(action="rescind").exists())
