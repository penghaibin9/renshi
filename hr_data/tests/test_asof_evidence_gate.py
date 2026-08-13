from datetime import date

from django.test import TestCase

from hr_data.models import AsOfEvidenceSnapshot
from hr_data.selectors import dashboard_snapshot


class Hr18AsOfEvidenceGateTests(TestCase):
    def _evidence(self, tenant_id, no, status):
        return AsOfEvidenceSnapshot.objects.create(
            tenant_id=tenant_id,
            evidence_no=no,
            definition_kind=AsOfEvidenceSnapshot.DefinitionKind.METRIC,
            definition_code="EDU-HR-01",
            definition_version=1,
            as_of_date=date(2026, 8, 1),
            status=status,
            source_statuses_json={"HR03": "OK", "HR13": "OK"},
            blocked_domains_json=[] if status == "COMPLETE" else ["HR13"],
            provider_versions_json={"HR03": "v1", "HR13": "v2"},
            provider_evidence_hashes_json={"HR03": "c" * 64, "HR13": "d" * 64},
            evidence_hash=("a" if tenant_id == 77 else "b") * 64,
        )

    def test_dashboard_exposes_real_asof_engine_and_tenant_scoped_evidence(self):
        self._evidence(77, "E-1", AsOfEvidenceSnapshot.Status.COMPLETE)
        self._evidence(77, "E-2", AsOfEvidenceSnapshot.Status.PARTIAL)
        self._evidence(88, "E-OTHER", AsOfEvidenceSnapshot.Status.COMPLETE)

        payload = dashboard_snapshot(77)

        self.assertTrue(payload["capabilities"]["submissionAsOfGate"])
        self.assertTrue(payload["capabilities"]["asOfEngine"])
        self.assertEqual(payload["summary"]["asOfEvidence"], 2)
        self.assertEqual(payload["summary"]["completeAsOfEvidence"], 1)
        self.assertEqual(payload["summary"]["blockedAsOfEvidence"], 1)
        self.assertEqual(
            {row["evidence_no"] for row in payload["recentAsOfEvidence"]},
            {"E-1", "E-2"},
        )
        self.assertTrue(
            all(row["definition_kind"] == "METRIC" for row in payload["recentAsOfEvidence"])
        )

    def test_complete_evidence_is_immutable(self):
        evidence = self._evidence(77, "E-IMMUTABLE", AsOfEvidenceSnapshot.Status.COMPLETE)
        evidence.status = AsOfEvidenceSnapshot.Status.PARTIAL
        with self.assertRaisesRegex(ValueError, "HR18_ASOF_EVIDENCE_IMMUTABLE"):
            evidence.save()
