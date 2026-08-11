"""Tenant-scoped read models for the HR18 data governance center."""
from .models import DataQualityFinding, MetricDefinitionVersion, SubmissionSnapshot


def dashboard_snapshot(tenant_id: int) -> dict:
    if not tenant_id:
        raise ValueError("tenant_id is required")
    tenant_id = int(tenant_id)
    metrics = MetricDefinitionVersion.objects.filter(tenant_id=tenant_id)
    findings = DataQualityFinding.objects.filter(tenant_id=tenant_id)
    submissions = SubmissionSnapshot.objects.filter(tenant_id=tenant_id)
    open_findings = findings.filter(status__in=["OPEN", "ACKNOWLEDGED"])
    return {
        "summary": {
            "metricVersions": metrics.count(),
            "currentMetrics": metrics.filter(status="PUBLISHED").count(),
            "openFindings": open_findings.count(),
            "criticalFindings": open_findings.filter(severity="CRITICAL").count(),
            "submissions": submissions.count(),
            "awaitingReceipt": submissions.filter(status="SUBMITTED", receipt_ref="").count(),
            "corrections": submissions.filter(status="CORRECTED").count(),
        },
        "recentFindings": list(findings.order_by("-detected_at")[:6].values(
            "id", "finding_no", "rule_code", "source_domain", "severity", "status", "detected_at"
        )),
        "recentSubmissions": list(submissions.order_by("-created_at")[:6].values(
            "id", "submission_no", "definition_code", "definition_version", "as_of_date", "status", "receipt_ref", "submitted_at"
        )),
        "capabilities": {
            "metricDefinition": True, "dataQualityFinding": True, "submissionSnapshot": True,
            "sourceGate": True, "populationDimension": False, "asOfEngine": False,
            "qualityRuleExecution": False, "asyncExchange": False, "submissionReceipt": False,
            "correctionWorkflow": False, "legacyReportTakeover": False,
        },
    }
