"""Lightweight legacy report write guard shared by report mutation views."""

from django.http import JsonResponse


def legacy_report_write_block_response(request):
    """Fail closed after an evidence-backed HR18 tenant cutover."""

    tenant_id = getattr(request, "tenant_id", None)
    if not tenant_id:
        return None

    from hr_data.services.legacy_report_asset_service import legacy_report_write_block

    block = legacy_report_write_block(tenant_id)
    if not block:
        return None
    return JsonResponse(
        {
            "error": "LEGACY_REPORT_WRITES_BLOCKED",
            "message": "HR18 正式接管后，旧报表模板只读，禁止继续写入。",
            "cutoverCode": block.cutover_step.cutover_code,
            "evidenceHash": block.evidence_hash,
        },
        status=409,
    )

