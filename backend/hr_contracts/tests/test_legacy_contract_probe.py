from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from hr_contracts.legacy_contract_probe import LegacyContractProbe


class LegacyContractProbeTests(SimpleTestCase):
    @patch("payroll.models.models.Contract.objects")
    def test_inventory_is_explicitly_tenant_scoped(self, contract_objects):
        scoped = MagicMock()
        scoped.count.return_value = 9
        scoped.filter.return_value.count.side_effect = [2, 4, 2, 1]
        contract_objects.filter.return_value = scoped

        report = LegacyContractProbe(tenant_id=77).inventory()

        contract_objects.filter.assert_called_once_with(
            employee_id__employee_work_info__company_id_id=77
        )
        self.assertEqual(report["total"], 9)
        self.assertFalse(report["authority"])

    @patch("payroll.models.models.Contract.objects")
    def test_snapshot_probe_is_bounded_and_never_claims_authority(self, contract_objects):
        scoped = MagicMock()
        ordered = MagicMock()
        values_qs = MagicMock()
        values_qs.__getitem__.return_value = [
            {
                "id": 1,
                "contract_name": "劳动合同",
                "employee_id_id": 12,
                "contract_start_date": None,
                "contract_end_date": None,
                "contract_status": "active",
                "department_id": 3,
                "job_position_id": 4,
                "job_role_id": 5,
                "shift_id": 6,
                "work_type_id": 7,
                "contract_document": "contracts/a.pdf",
            }
        ]
        contract_objects.filter.return_value = scoped
        scoped.order_by.return_value = ordered
        ordered.values.return_value = values_qs

        rows = LegacyContractProbe(tenant_id=77).list_snapshots(limit=5000)

        contract_objects.filter.assert_called_once_with(
            employee_id__employee_work_info__company_id_id=77
        )
        values_qs.__getitem__.assert_called_once_with(slice(None, 1000, None))
        self.assertFalse(rows[0]["authority"])
        self.assertEqual(rows[0]["fields"]["legacy_status"], "active")
        self.assertNotIn("wage", rows[0]["fields"])

    def test_tenant_is_required(self):
        with self.assertRaises(ValueError):
            LegacyContractProbe(tenant_id=0)
