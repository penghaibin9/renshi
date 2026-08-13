from hr_title import module_contract as contract


def test_hr13_contract_is_canonical():
    assert contract.MODULE_CODE == "HR13"
    assert contract.CANONICAL_API_PREFIX == "/api/v1/hr/titles"
    assert contract.PERMISSION_PREFIX == "hr.title"
    assert len(contract.CANONICAL_EVENTS) == len(set(contract.CANONICAL_EVENTS))
    assert "HR14" in contract.DOWNSTREAM_CONSUMERS
