from hr_changes import module_contract as contract


def test_hr06_module_contract_preserves_production_guards():
    assert contract.MODULE_CODE == "HR06"
    assert contract.APP_LABEL == "hr_changes"
    assert contract.CANONICAL_API_ROOT == "/api/v1/hr"
    assert "Person Transition Lock" in contract.REQUIRED_GUARDS
    assert "Outbox/Inbox 可靠事件" in contract.REQUIRED_GUARDS
    assert contract.FORBIDDEN_DIRECT_WRITES
