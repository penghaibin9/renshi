"""Exact metadata-only checks for the isolated HR03 import acceptance lane.

Business writes remain once-only. Read audits reflect each successful access.
This module never writes business data and does not weaken the API audit policy.
"""
from collections import Counter
import re
import uuid


def require(condition, message):
    if not condition:
        raise AssertionError(message)


IMPORT_AUDIT_ACTIONS = (
    "StaffImportValidated", "PersonCreated", "StaffMasterCreated",
    "EmploymentRelationshipStarted", "AssignmentCreated", "StaffImportRowCommitted",
    "StaffImportCompleted", "StaffImportIssuesDownloaded",
)


def successful_error_downloads(server_log: str, job_id: str) -> int:
    """Count successful HTTP accesses, not clicks or browser download events.

    A browser/transport may request the same attachment again. Each successful
    access must stay audited; read logs are not idempotent business mutations.
    Only the exact job endpoint, method and successful status count. A foreign
    school's 404 or the template endpoint cannot justify an extra audit row.
    """
    canonical_id = str(uuid.UUID(str(job_id)))
    target = re.escape(f"/api/v1/hr/staff/import/{canonical_id}/errors")
    pattern = rf'"GET {target} HTTP/1\.[01]" 200 [0-9]+[ \t]*$'
    count = len(re.findall(pattern, server_log, flags=re.MULTILINE))
    require(count > 0, "No successful exact-job error-workbook access in server evidence")
    return count


def audit_proof(rows, *, tenant_id, actor_id, job_id, staff_id, person_id,
                committed_row_no, download_accesses):
    """Exact audit/action/subject proof over safe database metadata only.

    The seven write actions remain exactly once. Access audits equal the
    independently observed successful requests, not an unrestricted >= check.
    No names, identity documents, reason text, tokens or request cookies leave
    the database through this diagnostic.
    """
    rows = list(rows)
    require(isinstance(download_accesses, int) and not isinstance(download_accesses, bool)
            and download_accesses > 0, "Invalid successful download count")
    counts = Counter(row["action"] for row in rows)
    expected = {action: 1 for action in IMPORT_AUDIT_ACTIONS}
    expected["StaffImportIssuesDownloaded"] = download_accesses
    result = {
        "status": "FAIL", "mutationEventsExpected": 7,
        "successfulDownloadRequests": download_accesses,
        "expectedActionCounts": expected, "actualActionCounts": dict(counts),
        "auditRows": len(rows), "errors": [],
    }
    problems = result["errors"]
    if dict(counts) != expected:
        problems.append("Audit action counts do not match writes and successful accesses")
    if len({str(row["id"]) for row in rows}) != len(rows):
        problems.append("Duplicate audit event identifier")
    source_id = f"import:{job_id}:row:{committed_row_no}"
    job_actions = {"StaffImportValidated", "StaffImportCompleted", "StaffImportIssuesDownloaded"}
    for row in rows:
        action = row["action"]
        if row["tenant_id"] != tenant_id or row["actor_user_id"] != actor_id:
            problems.append(f"{action}: wrong or missing audit tenant/actor")
        if action == "PersonCreated" and str(row["person_id"]) != str(person_id):
            problems.append(f"{action}: wrong person reference")
        if action in {"StaffMasterCreated", "EmploymentRelationshipStarted", "AssignmentCreated",
                      "StaffImportRowCommitted"} and str(row["staff_id"]) != str(staff_id):
            problems.append(f"{action}: wrong staff reference")
        if action in job_actions:
            if row["business_type"] != "STAFF_IMPORT" or row["business_id"] != str(job_id):
                problems.append(f"{action}: wrong import job reference")
        elif action in {"EmploymentRelationshipStarted", "AssignmentCreated"}:
            if row["business_type"] != "MIGRATION_VERIFIED" or row["business_id"] != source_id:
                problems.append(f"{action}: wrong source row reference")
        elif action == "StaffImportRowCommitted":
            if row["business_type"] != "STAFF_IMPORT" or row["business_id"] != source_id:
                problems.append(f"{action}: wrong import row reference")
    if not problems:
        result["status"] = "PASS"
    return result
