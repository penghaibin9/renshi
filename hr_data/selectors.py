"""Tenant-scoped read models for the HR18 data governance center."""
from .models import (
    AsOfEvidenceSnapshot,
    DataQualityFinding,
    DimensionDefinitionVersion,
    MetricDefinitionVersion,
    PopulationDefinitionVersion,
    SubmissionSnapshot,
)


def dashboard_snapshot(tenant_id: int) -> dict:
    if not tenant_id:
        raise ValueError("tenant_id is required")
    tenant_id = int(tenant_id)
    populations = PopulationDefinitionVersion.objects.filter(tenant_id=tenant_id)
    dimensions = DimensionDefinitionVersion.objects.filter(tenant_id=tenant_id)
    metrics = MetricDefinitionVersion.objects.filter(tenant_id=tenant_id)
    findings = DataQualityFinding.objects.filter(tenant_id=tenant_id)
    evidences = AsOfEvidenceSnapshot.objects.filter(tenant_id=tenant_id)
    submissions = SubmissionSnapshot.objects.filter(tenant_id=tenant_id)
    open_findings = findings.filter(status__in=["OPEN", "ACKNOWLEDGED"])
    return {
        "summary": {
            "populationVersions": populations.count(),
            "populationCodes": populations.values("population_code").distinct().count(),
            "dimensionVersions": dimensions.count(),
            "dimensionCodes": dimensions.values("dimension_code").distinct().count(),
            "metricVersions": metrics.count(),
            "metricCodes": metrics.values("metric_code").distinct().count(),
            "asOfEvidence": evidences.count(),
            "completeAsOfEvidence": evidences.filter(status=AsOfEvidenceSnapshot.Status.COMPLETE).count(),
            "blockedAsOfEvidence": evidences.exclude(status=AsOfEvidenceSnapshot.Status.COMPLETE).count(),
            "openFindings": open_findings.count(),
            "criticalFindings": open_findings.filter(severity="CRITICAL").count(),
            "submissions": submissions.count(),
            "dispatchQueued": submissions.filter(status=SubmissionSnapshot.Status.DISPATCH_QUEUED).count(),
            "dispatchFailed": submissions.filter(status=SubmissionSnapshot.Status.DISPATCH_FAILED).count(),
            "awaitingReceipt": submissions.filter(status=SubmissionSnapshot.Status.SUBMITTED, receipt_ref="").count(),
            "acceptedReceipts": submissions.filter(status=SubmissionSnapshot.Status.ACCEPTED).exclude(receipt_ref="").count(),
            "rejectedReceipts": submissions.filter(status=SubmissionSnapshot.Status.REJECTED).exclude(receipt_ref="").count(),
            "corrections": submissions.filter(status=SubmissionSnapshot.Status.CORRECTED).count(),
        },
        "recentPopulations": list(
            populations.order_by("population_code", "-version_no")[:12].values(
                "id", "population_code", "name", "version_no", "status", "root_domain",
                "predicate_json", "source_domains", "as_of_required", "updated_at"
            )
        ),
        "recentDimensions": list(
            dimensions.order_by("dimension_code", "-version_no")[:12].values(
                "id", "dimension_code", "name", "version_no", "status", "source_domain",
                "attribute_path", "value_type", "label_map_json", "as_of_required", "updated_at"
            )
        ),
        "recentMetrics": list(
            metrics.order_by("metric_code", "-version_no")[:12].values(
                "id", "metric_code", "name", "version_no", "status", "value_type", "unit",
                "population_code", "source_domains", "as_of_required", "updated_at"
            )
        ),
        "recentAsOfEvidence": list(
            evidences.order_by("-generated_at")[:16].values(
                "id", "evidence_no", "definition_kind", "definition_code", "definition_version",
                "as_of_date", "status", "source_statuses_json", "blocked_domains_json",
                "provider_versions_json", "provider_evidence_hashes_json", "evidence_hash", "generated_at"
            )
        ),
        "recentFindings": list(
            findings.order_by("-detected_at")[:12].values(
                "id", "finding_no", "rule_code", "source_domain", "source_object_ref",
                "severity", "status", "detected_at", "resolved_at"
            )
        ),
        "recentSubmissions": list(
            submissions.order_by("-created_at")[:12].values(
                "id", "submission_no", "definition_kind", "definition_code", "definition_version",
                "as_of_date", "scope_json", "status", "dispatch_ref", "dispatch_requested_at",
                "dispatch_error", "receipt_ref", "submitted_at", "parent_submission_id", "created_at"
            )
        ),
        "capabilities": {
            "metricDefinition": True,
            "dataQualityFinding": True,
            "submissionSnapshot": True,
            "sourceGate": True,
            "populationDimension": True,
            "submissionAsOfGate": True,
            "asOfEngine": True,
            "qualityRuleExecution": False,
            "asyncSubmissionDispatch": True,
            "asyncExchange": False,
            "submissionReceipt": True,
            "correctionWorkflow": False,
            "legacyReportTakeover": False,
        },
    }
