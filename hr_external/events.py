"""Canonical HR08 business events for external workforce consumers."""

from horilla.hr_event_registry import BusinessEventDefinition, register_business_events

EVENT_HIRING_SUBMITTED = "hr.external.hiring.submitted"
EVENT_HIRING_APPROVED = "hr.external.hiring.approved"
EVENT_ENGAGEMENT_ACTIVATED = "hr.external.engagement.activated"
EVENT_ASSIGNMENT_CREATED = "hr.external.assignment.created"
EVENT_TASK_ASSIGNED = "hr.external.task.assigned"
EVENT_TASK_COMPLETED = "hr.external.task.completed"
EVENT_WORKLOAD_VERIFIED = "hr.external.workload.verified"
EVENT_RENEWAL_DUE = "hr.external.renewal.due"
EVENT_ENGAGEMENT_RENEWED = "hr.external.engagement.renewed"
EVENT_ENGAGEMENT_ENDING = "hr.external.engagement.ending"
EVENT_ENGAGEMENT_ENDED = "hr.external.engagement.ended"
EVENT_ACCESS_REVOCATION_REQUESTED = "hr.external.access.revocation_requested"
EVENT_ACCESS_REVOKED = "hr.external.access.revoked"

EVENT_DEFINITIONS = (
    BusinessEventDefinition(EVENT_HIRING_SUBMITTED, "HR08", "hiring", 1, "外聘申请已提交"),
    BusinessEventDefinition(EVENT_HIRING_APPROVED, "HR08", "hiring", 1, "外聘申请已批准"),
    BusinessEventDefinition(EVENT_ENGAGEMENT_ACTIVATED, "HR08", "engagement", 1, "外聘聘任已激活"),
    BusinessEventDefinition(EVENT_ASSIGNMENT_CREATED, "HR08", "assignment", 1, "外聘派任已创建"),
    BusinessEventDefinition(EVENT_TASK_ASSIGNED, "HR08", "task", 1, "外聘任务已分派"),
    BusinessEventDefinition(EVENT_TASK_COMPLETED, "HR08", "task", 1, "外聘任务已完成"),
    BusinessEventDefinition(EVENT_WORKLOAD_VERIFIED, "HR08", "workload", 1, "外聘工作量已核验"),
    BusinessEventDefinition(EVENT_RENEWAL_DUE, "HR08", "renewal", 1, "外聘续聘评审已到期"),
    BusinessEventDefinition(EVENT_ENGAGEMENT_RENEWED, "HR08", "engagement", 1, "外聘聘任已续期"),
    BusinessEventDefinition(EVENT_ENGAGEMENT_ENDING, "HR08", "engagement", 1, "外聘聘任进入终止处理"),
    BusinessEventDefinition(EVENT_ENGAGEMENT_ENDED, "HR08", "engagement", 1, "外聘聘任已终止"),
    BusinessEventDefinition(EVENT_ACCESS_REVOCATION_REQUESTED, "HR08", "access", 1, "外聘权限回收已请求"),
    BusinessEventDefinition(EVENT_ACCESS_REVOKED, "HR08", "access", 1, "外聘权限已回收"),
)
register_business_events(EVENT_DEFINITIONS)
