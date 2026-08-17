from hr_time import module_contract as contract


def test_hr11_module_contract_is_canonical():
    assert contract.MODULE_CODE == "HR11"
    assert contract.APP_LABEL == "hr_time"
    assert contract.CANONICAL_API_ROOT == "/api/v1/hr"
    assert contract.REQUIRED_GUARDS
    assert contract.FORBIDDEN_DIRECT_WRITES
