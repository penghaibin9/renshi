import re
from pathlib import Path

from django.test import SimpleTestCase


def _normalized_name(value):
    return re.sub(r"[-_.]+", "-", value).lower()


class DependencyLockContractTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.root = Path(__file__).resolve().parents[2]
        cls.direct = (cls.root / "requirements.txt").read_text(encoding="utf-8")
        cls.lock = (cls.root / "requirements.lock").read_text(encoding="utf-8")

    @staticmethod
    def _requirement_lines(source):
        return [
            line.strip()
            for line in source.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]

    def test_lock_contains_only_exact_unique_versions(self):
        locked = self._requirement_lines(self.lock)
        self.assertGreater(len(locked), 0)
        self.assertTrue(all(line.count("==") == 1 for line in locked))
        names = [_normalized_name(line.split("==", 1)[0]) for line in locked]
        self.assertEqual(len(names), len(set(names)))

    def test_every_direct_dependency_is_present_in_lock(self):
        locked_names = {
            _normalized_name(line.split("==", 1)[0])
            for line in self._requirement_lines(self.lock)
        }
        direct_names = {
            _normalized_name(re.match(r"^[A-Za-z0-9_.-]+", line).group(0))
            for line in self._requirement_lines(self.direct)
        }
        self.assertSetEqual(direct_names - locked_names, set())

    def test_production_image_installs_the_lock(self):
        dockerfile = (self.root / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("COPY requirements.txt requirements.lock ./", dockerfile)
        self.assertIn("-r requirements.lock", dockerfile)
        self.assertNotIn("-r requirements.txt", dockerfile)

    def test_pdfkit_is_not_a_production_dependency(self):
        direct_names = {
            _normalized_name(re.match(r"^[A-Za-z0-9_.-]+", line).group(0))
            for line in self._requirement_lines(self.direct)
        }
        locked_names = {
            _normalized_name(line.split("==", 1)[0])
            for line in self._requirement_lines(self.lock)
        }
        self.assertNotIn("pdfkit", direct_names)
        self.assertNotIn("pdfkit", locked_names)

    def test_django_contains_security_patch(self):
        self.assertIn("Django==5.2.17", self.direct)
        self.assertIn("Django==5.2.17", self.lock)
