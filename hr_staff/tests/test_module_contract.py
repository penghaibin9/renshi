from hr_staff import module_contract as contract


def test_hr03_module_contract_is_canonical():
    assert contract.MODULE_CODE == "HR03"
    assert contract.APP_LABEL == "hr_staff"
    assert contract.CANONICAL_API_ROOT == "/api/v1/hr"
    assert "教职工身份主档" in contract.OWNS
    assert contract.FORBIDDEN_DIRECT_WRITES
