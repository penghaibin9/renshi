from hr_external import module_contract as contract


def test_hr08_module_contract_is_canonical():
    assert contract.MODULE_CODE == "HR08"
    assert contract.APP_LABEL == "hr_external"
    assert contract.CANONICAL_API_ROOT == "/api/v1/hr"
    assert contract.REQUIRED_GUARDS
    assert contract.FORBIDDEN_DIRECT_WRITES
