from hr_control_center import module_contract as contract


def test_hr01_module_contract_is_canonical():
    assert contract.MODULE_CODE == "HR01"
    assert contract.APP_LABEL == "hr_control_center"
    assert contract.CANONICAL_API_ROOT == "/api/v1/hr"
    assert "/api/hr/v1" in contract.LEGACY_API_ROOTS
    assert contract.FORBIDDEN_DIRECT_WRITES
