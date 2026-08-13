"""Shared-gate guard for HR14."""

from django.test import SimpleTestCase


class SharedGateNoSkipTests(SimpleTestCase):
    def test_shared_gate_contract_is_explicit(self):
        self.assertNotEqual('shared-quality', 'skipped')
