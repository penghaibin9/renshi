"""Canonical HR09 qualification and recognition business events."""

from horilla.hr_event_registry import BusinessEventDefinition, register_business_events

EVENT_CREDENTIAL_SUBMITTED = "hr.qualification.credential.submitted"
EVENT_CREDENTIAL_VERIFIED = "hr.qualification.credential.verified"
EVENT_CREDENTIAL_EXPIRED = "hr.qualification.credential.expired"
EVENT_CREDENTIAL_REVOKED = "hr.qualification.credential.revoked"
EVENT_BATCH_PUBLISHED = "hr.qualification.batch.published"
EVENT_APPLICATION_SUBMITTED = "hr.qualification.application.submitted"
EVENT_EVIDENCE_INVALIDATED = "hr.qualification.evidence.invalidated"
EVENT_RECOGNITION_GRANTED = "hr.qualification.recognition.granted"
EVENT_RECOGNITION_RECHECK_DUE = "hr.qualification.recognition.recheck_due"
EVENT_RECOGNITION_REVOKED = "hr.qualification.recognition.revoked"
EVENT_RISK_OPENED = "hr.qualification.risk.opened"
EVENT_RESULT_EFFECTIVE = "hr.qualification.result.effective"

EVENT_DEFINITIONS = (
    BusinessEventDefinition(EVENT_CREDENTIAL_SUBMITTED, "HR09", "credential", 1, "资格证据已提交核验"),
    BusinessEventDefinition(EVENT_CREDENTIAL_VERIFIED, "HR09", "credential", 1, "资格证据已核验"),
    BusinessEventDefinition(EVENT_CREDENTIAL_EXPIRED, "HR09", "credential", 1, "资格事实已到期"),
    BusinessEventDefinition(EVENT_CREDENTIAL_REVOKED, "HR09", "credential", 1, "资格事实已撤销"),
    BusinessEventDefinition(EVENT_BATCH_PUBLISHED, "HR09", "batch", 1, "双师型认定批次已发布"),
    BusinessEventDefinition(EVENT_APPLICATION_SUBMITTED, "HR09", "application", 1, "双师型申请已提交"),
    BusinessEventDefinition(EVENT_EVIDENCE_INVALIDATED, "HR09", "evidence", 1, "双师型依赖证据已失效"),
    BusinessEventDefinition(EVENT_RECOGNITION_GRANTED, "HR09", "recognition", 1, "双师型正式认定已授予"),
    BusinessEventDefinition(EVENT_RECOGNITION_RECHECK_DUE, "HR09", "recognition", 1, "双师型认定需要复核"),
    BusinessEventDefinition(EVENT_RECOGNITION_REVOKED, "HR09", "recognition", 1, "双师型正式认定已撤销"),
    BusinessEventDefinition(EVENT_RISK_OPENED, "HR09", "risk", 1, "资格或双师型风险已开启"),
    BusinessEventDefinition(EVENT_RESULT_EFFECTIVE, "HR09", "result", 1, "资格认定结果已生效"),
)
register_business_events(EVENT_DEFINITIONS)
