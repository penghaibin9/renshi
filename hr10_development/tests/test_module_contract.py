from django.apps import apps

from hr10_development import module_contract as contract
from hr10_development.models import HrDevelopmentImportJob, HrDevelopmentStagingRow


def test_hr10_module_contract_is_canonical():
    assert contract.MODULE_CODE == "HR10"
    assert contract.APP_LABEL == "hr10_development"
    assert contract.CANONICAL_API_ROOT == "/api/v1/hr"
    assert contract.REQUIRED_GUARDS


def test_legacy_takeover_models_remain_registered_with_django():
    assert HrDevelopmentStagingRow.__name__ == "HrDevelopmentStagingRow"
    assert HrDevelopmentImportJob.__name__ == "HrDevelopmentImportJob"
    assert apps.get_model("hr10_development", "HrDevelopmentStagingRow") is HrDevelopmentStagingRow
    assert apps.get_model("hr10_development", "HrDevelopmentImportJob") is HrDevelopmentImportJob
