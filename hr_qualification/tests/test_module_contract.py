from hr_qualification import module_contract as contract


def test_hr09_module_contract_is_canonical():
    assert contract.MODULE_CODE == "HR09"
    assert contract.APP_LABEL == "hr_qualification"
    assert contract.CANONICAL_API_ROOT == "/api/v1/hr"
    assert contract.REQUIRED_GUARDS
    assert contract.FORBIDDEN_DIRECT_WRITES
