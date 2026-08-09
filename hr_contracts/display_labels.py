"""HR07 contract display labels and CSS classes for template tags."""

LIFECYCLE_CLASS = {
    "DRAFT": "oh-badge oh-badge--secondary",
    "PENDING_SIGNING": "oh-badge oh-badge--info",
    "ACTIVE": "oh-badge oh-badge--success",
    "EXPIRING_SOON": "oh-badge oh-badge--warning",
    "REVIEW_DUE": "oh-badge oh-badge--warning",
    "RENEWAL_IN_PROGRESS": "oh-badge oh-badge--info",
    "NON_RENEWAL": "oh-badge oh-badge--danger",
    "TERMINATED": "oh-badge oh-badge--danger",
    "EXPIRED": "oh-badge oh-badge--neutral",
    "AMENDED": "oh-badge oh-badge--info",
    "ARCHIVED": "oh-badge oh-badge--neutral",
}

SEVERITY_CLASS = {
    "CRITICAL": "oh-badge oh-badge--danger",
    "HIGH": "oh-badge oh-badge--warning",
    "MEDIUM": "oh-badge oh-badge--info",
    "LOW": "oh-badge oh-badge--success",
}

_LABELS = {
    "lifecycle_status": {
        "DRAFT": "草稿", "PENDING_SIGNING": "待签署", "ACTIVE": "履行中",
        "EXPIRING_SOON": "即将到期", "REVIEW_DUE": "待评审", "RENEWAL_IN_PROGRESS": "续签中",
        "NON_RENEWAL": "不续签", "TERMINATED": "已解除", "EXPIRED": "已到期",
        "AMENDED": "已变更", "ARCHIVED": "已归档",
    },
    "agreement_family": {"PRIMARY_EMPLOYMENT": "正式聘用", "SECONDARY_EMPLOYMENT": "兼聘", "EXTERNAL_ENGAGEMENT": "外聘协议", "TEMPORARY": "临时", "OTHER": "其他"},
    "risk_severity": {"CRITICAL": "严重", "HIGH": "高", "MEDIUM": "中", "LOW": "低"},
    "signature_envelope_status": {"DRAFT": "草稿", "SENT": "已发送", "COMPLETED": "已完成", "DECLINED": "已拒绝", "FAILED": "失败", "EXPIRED": "已过期"},
    "template_status": {"DRAFT": "草稿", "ACTIVE": "生效", "RETIRED": "已停用"},
}


def label(category, key, default=""):
    return _LABELS.get(category, {}).get(str(key), key if not default else default)
