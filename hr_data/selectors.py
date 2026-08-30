"""Tenant-scoped read models for the HR18 data governance center."""
from .models import (
    AsOfEvidenceSnapshot,
    DataQualityFinding,
    DataQualityRuleVersion,
    DataQualityRun,
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
    quality_rules = DataQualityRuleVersion.objects.filter(tenant_id=tenant_id)
    quality_runs = DataQualityRun.objects.filter(tenant_id=tenant_id)
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
            "qualityRuleVersions": quality_rules.count(),
            "qualityRuleCodes": quality_rules.values("rule_code").distinct().count(),
            "qualityRuns": quality_runs.count(),
            "qualityUnavailableRuns": quality_runs.filter(status=DataQualityRun.Status.UNAVAILABLE).count(),
            "qualityErrorRuns": quality_runs.filter(status=DataQualityRun.Status.ERROR).count(),
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
                "id", "population_code", "name", "version_no", "status", "root_domain", "grain",
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
        "recentQualityRules": list(
            quality_rules.order_by("rule_code", "-version_no")[:12].values(
                "id", "rule_code", "name", "version_no", "status", "source_domain",
                "severity", "parameters_json", "as_of_required", "content_hash", "updated_at"
            )
        ),
        "recentQualityRuns": list(
            quality_runs.order_by("-executed_at")[:16].values(
                "id", "run_no", "rule_code", "rule_version", "source_domain", "as_of_date",
                "status", "provider_version", "evidence_hash", "finding_count", "error_message",
                "executed_at"
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
                "id", "finding_no", "quality_run_id", "rule_code", "rule_version", "source_domain",
                "source_object_ref", "finding_fingerprint", "severity", "details_json", "status",
                "detected_at", "resolved_at"
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
            "qualityFindingLifecycle": True,
            "submissionSnapshot": True,
            "sourceGate": True,
            "populationDimension": True,
            "populationGrain": True,
            "submissionAsOfGate": True,
            "asOfEvidenceEngine": True,
            "asOfEngine": True,
            "hr03CountEvaluation": True,
            "hr03AssignmentCountEvaluation": True,
            "formalFactProviderEvidence": True,
            "formalFactPersonCountEvaluation": True,
            # General expression evaluation is not implemented; historical values
            # remain intentionally limited to bounded COUNT evaluators.
            "metricEvaluation": False,
            "qualityRuleExecution": True,
            "builtinHr03QualityProvider": True,
            "asyncSubmissionDispatch": True,
            "asyncExchange": True,
            "submissionReceipt": True,
            "correctionWorkflow": True,
            "legacyReportTakeover": False,
        },
    }
