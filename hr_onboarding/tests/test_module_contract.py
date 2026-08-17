from hr_onboarding import module_contract as contract


def test_hr05_module_contract_is_canonical():
    assert contract.MODULE_CODE == "HR05"
    assert contract.APP_LABEL == "hr_onboarding"
    assert contract.CANONICAL_API_ROOT == "/api/v1/hr"
    assert contract.HANDOFF_TARGETS
    assert contract.FORBIDDEN_DIRECT_WRITES
