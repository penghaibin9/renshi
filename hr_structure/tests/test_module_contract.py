from hr_structure import module_contract as contract


def test_hr02_module_contract_is_canonical():
    assert contract.MODULE_CODE == "HR02"
    assert contract.APP_LABEL == "hr_structure"
    assert contract.CANONICAL_API_ROOT == "/api/v1/hr"
    assert contract.OWNS
    assert contract.FORBIDDEN_DIRECT_WRITES
