"""HR12 Assessment — 可观测性指标定义（S11.2）。"""

ASSESSMENT_METRICS = {
    "assessment_cycle_active_total": {
        "type": "gauge",
        "help": "当前活跃的考核周期数",
        "labels": ["tenant_id", "assessment_type"],
    },
    "assessment_case_by_status": {
        "type": "gauge",
        "help": "各状态下的考核 Case 数量",
        "labels": ["tenant_id", "assessment_type", "status"],
    },
    "assessment_policy_ambiguous_total": {
        "type": "counter",
        "help": "考核政策冲突次数",
        "labels": ["tenant_id"],
    },
    "assessment_population_gap_total": {
        "type": "gauge",
        "help": "应考未入人群的人数",
        "labels": ["tenant_id", "cycle_id"],
    },
    "assessment_provider_unavailable_total": {
        "type": "counter",
        "help": "Provider 不可用次数",
        "labels": ["tenant_id", "provider_name"],
    },
    "assessment_evidence_conflict_total": {
        "type": "counter",
        "help": "证据冲突次数",
        "labels": ["tenant_id"],
    },
    "assessment_reviewer_overdue_total": {
        "type": "gauge",
        "help": "超期未完成评审人数",
        "labels": ["tenant_id", "cycle_id"],
    },
    "assessment_quota_blocker_total": {
        "type": "gauge",
        "help": "配额超额阻塞次数",
        "labels": ["tenant_id", "cycle_id"],
    },
    "assessment_finalization_failed_total": {
        "type": "counter",
        "help": "审定失败次数",
        "labels": ["tenant_id"],
    },
    "assessment_result_revision_total": {
        "type": "counter",
        "help": "结果修订次数",
        "labels": ["tenant_id", "revision_type"],
    },
    "assessment_objection_open_total": {
        "type": "gauge",
        "help": "当前开放异议数",
        "labels": ["tenant_id"],
    },
    "assessment_downstream_delivery_failed_total": {
        "type": "counter",
        "help": "下游事件投递失败次数",
        "labels": ["tenant_id", "consumer_domain"],
    },
    "assessment_legacy_drift_total": {
        "type": "gauge",
        "help": "Legacy vs HR12 数据漂移量",
        "labels": ["tenant_id", "metric"],
    },
}
