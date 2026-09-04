from django.test import TestCase

from hr_changes.selectors.bootstrap_data import BootstrapDataSelector


class IdentityBootstrapContractTests(TestCase):
    def test_identity_options_are_controlled_hr03_machine_values_with_chinese_labels(self):
        options = BootstrapDataSelector(tenant_id=1).identity_options()
        categories = {item["code"]: item["label"] for item in options["staffCategories"]}
        relationships = {item["code"]: item["label"] for item in options["relationshipTypes"]}
        employment = {item["code"]: item["label"] for item in options["employmentTypes"]}

        self.assertEqual(categories["TEACHER"], "教师")
        self.assertEqual(categories["ADMIN"], "行政管理")
        self.assertEqual(relationships["REGULAR_EMPLOYMENT"], "正式聘用")
        self.assertEqual(relationships["CONTRACT"], "合同制")
        self.assertEqual(employment["FULL_TIME"], "全职")
        self.assertEqual(employment["PART_TIME"], "兼职")
