from hr_assessment import module_contract as contract


def test_hr12_module_contract_is_canonical():
    assert contract.MODULE_CODE == "HR12"
    assert contract.APP_LABEL == "hr_assessment"
    assert contract.CANONICAL_API_ROOT == "/api/v1/hr"
    assert contract.REQUIRED_GUARDS
    assert contract.FORBIDDEN_DIRECT_WRITES
    assert len(contract.STABLE_NAMED_CONSTRAINTS) == 3
