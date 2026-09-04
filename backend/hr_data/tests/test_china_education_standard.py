from datetime import date, timedelta

from django.test import SimpleTestCase

from hr_data.standards.china_education import (
    ChinaEducationStandardError,
    normalize_exchange_schema,
    standard_catalog,
)


def schema_with_profile(**classification_overrides):
    classification = {
        "primaryCategory": "教职工数据",
        "secondaryCategory": "教职工管理数据",
        "securityLevel": "L3",
        "scope": "WHOLE_UNIVERSITY",
        "containsSensitivePersonalInformation": True,
        "classificationBasis": "覆盖全校教职工的人事管理数据，按就高从严原则定为 L3。",
        "classifiedAt": date.today().isoformat(),
    }
    classification.update(classification_overrides)
    return {
        "fields": [{"name": "staffNo", "type": "string"}],
        "standardProfile": {
            "profileCode": "CHINA_HIGHER_EDUCATION_HR",
            "semanticStandards": [{"code": "client-controlled"}],
            "classification": classification,
        },
    }


class ChinaEducationStandardTests(SimpleTestCase):
    def test_server_canonicalizes_current_standards_and_freeze_evidence(self):
        normalized = normalize_exchange_schema(schema_with_profile(), record_count=8312)
        profile = normalized["standardProfile"]
        self.assertEqual(profile["semanticStandards"][0]["code"], "GB/T 29808-2013")
        self.assertEqual(profile["classificationStandard"]["code"], "JY/T 0661-2025")
        self.assertEqual(profile["classification"]["recordCountAtFreeze"], 8312)
        self.assertEqual(profile["classification"]["securityLevelName"], "一般数据（三级）")

    def test_whole_university_staff_dataset_cannot_be_downgraded_below_l3(self):
        with self.assertRaises(ChinaEducationStandardError) as caught:
            normalize_exchange_schema(
                schema_with_profile(securityLevel="L2"), record_count=2000
            )
        self.assertEqual(caught.exception.code, "EXCHANGE_CLASSIFICATION_LEVEL_TOO_LOW")

    def test_important_or_core_data_requires_approval_reference(self):
        with self.assertRaises(ChinaEducationStandardError) as caught:
            normalize_exchange_schema(
                schema_with_profile(securityLevel="L4"), record_count=2000
            )
        self.assertEqual(caught.exception.code, "EXCHANGE_CLASSIFICATION_APPROVAL_REQUIRED")

    def test_future_classification_date_is_rejected(self):
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        with self.assertRaises(ChinaEducationStandardError) as caught:
            normalize_exchange_schema(
                schema_with_profile(classifiedAt=tomorrow), record_count=1
            )
        self.assertEqual(caught.exception.code, "EXCHANGE_CLASSIFIED_AT_INVALID")

    def test_legacy_or_non_education_schema_remains_supported(self):
        schema = {"fields": [{"name": "staffNo", "type": "string"}]}
        self.assertEqual(normalize_exchange_schema(schema, record_count=1), schema)

    def test_catalog_uses_chinese_higher_education_labels(self):
        catalog = standard_catalog()
        self.assertEqual(catalog["wholeUniversityStaffMinimumLevel"], "L3")
        self.assertEqual(catalog["categories"][0]["primary"], "教职工数据")
