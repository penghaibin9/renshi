from hr_recruitment import module_contract as contract


def test_hr04_module_contract_is_canonical():
    assert contract.MODULE_CODE == "HR04"
    assert contract.APP_LABEL == "hr_recruitment"
    assert contract.CANONICAL_API_ROOT == "/api/v1/hr"
    assert contract.HANDOFF_TARGETS
    assert contract.FORBIDDEN_DIRECT_WRITES
