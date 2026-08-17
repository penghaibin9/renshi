"""HR07 business-event definitions registered in the global event contract."""

from horilla.hr_event_registry import BusinessEventDefinition, register_business_events

EVENT_AGREEMENT_CREATED = "hr.contracts.agreement.created"
EVENT_AGREEMENT_SIGNED = "hr.contracts.agreement.signed"
EVENT_AGREEMENT_EFFECTIVE = "hr.contracts.agreement.effective"

EVENT_DEFINITIONS = (
    BusinessEventDefinition(
        EVENT_AGREEMENT_CREATED, "HR07", "agreement", 1, "合同主档创建"
    ),
    BusinessEventDefinition(
        EVENT_AGREEMENT_SIGNED, "HR07", "agreement", 1, "首个合同版本完成签署并冻结"
    ),
    BusinessEventDefinition(
        EVENT_AGREEMENT_EFFECTIVE, "HR07", "agreement", 1, "已签署合同版本正式生效"
    ),
)
register_business_events(EVENT_DEFINITIONS)
