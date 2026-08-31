from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


class Hr06PagePermissionContractTests(SimpleTestCase):
    def test_server_rendered_workspaces_match_canonical_permission_boundaries(self):
        source = (Path(settings.BASE_DIR) / "hr_changes/views.py").read_text(encoding="utf-8")
        expected = {
            "change_center": "hr.change.view",
            "change_new": "hr.change.transfer.create",
            "future_changes": "hr.change.view",
            "change_detail": "hr.change.view",
            "transfers": "hr.change.transfer.create",
            "job_identity": "hr.change.identity_change.create",
            "secondments": "hr.change.temporary.create",
            "ledger": "hr.change.ledger.view",
            "change_preview": "hr.change.submit",
        }
        for function_name, permission in expected.items():
            marker = f'@require_hr_change_permission("{permission}")\ndef {function_name}'
            self.assertIn(marker, source, function_name)

    def test_generic_collection_get_has_explicit_view_gate(self):
        source = (Path(settings.BASE_DIR) / "hr_changes/api/collection.py").read_text(encoding="utf-8")
        self.assertIn('request.user.has_perm("hr.change.view")', source)
        self.assertIn('"PERMISSION_DENIED"', source)
        self.assertIn("return changes_api.change_list(request)", source)
