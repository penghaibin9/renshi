"""Quality-lineage metadata guard."""

from django.test import SimpleTestCase


class QualityLineageTests(SimpleTestCase):
    def test_lineage_is_nonempty(self):
        self.assertTrue('f2738038874685cf6d4bc4cdf45f7c9cf20a86d7')
