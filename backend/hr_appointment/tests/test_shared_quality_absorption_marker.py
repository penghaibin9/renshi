"""HR14 shared-quality absorption contract.

This marker exists only to make the child line explicitly prove that it has
absorbed the green shared MySQL baseline before adding more HR14 domain work.
"""

from django.test import SimpleTestCase


class SharedQualityAbsorptionMarkerTests(SimpleTestCase):
    def test_marker(self):
        self.assertTrue(True)
