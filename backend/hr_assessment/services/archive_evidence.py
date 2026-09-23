"""Frozen HR12 archive projections, adapted from user-provided NonDegree R11.

Origin: backend/app/assessment_evidence.py::verified_archive/attachment_index
and assessment_projection. See docs/r11_fusion/PROVENANCE.md for exact hashes.

Use HR12's models, authority snapshots and permission boundary. No FastAPI,
SQLAlchemy, R11 identities, training amounts or replacement migration graph.
Historical gaps remain gaps. Read/print/export never fetch today's HR09/HR03
values to embellish yesterday's evidence. Hashes detect accidental/tampered
content, not a trusted administrator who can replace both payload and hash.
"""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, InvalidOperation
import hashlib
import hmac
import json
import re

from django.db import transaction
from hr_assessment.models import (
    HrAssessmentCase, HrCycleSnapshot, HrProviderSnapshotSet, HrProviderSnapshotItem,
    HrSubjectSnapshot, HrAssessmentDocument,
)
from hr_assessment.models.result import HrResultRevision
from hr_assessment.services.result_correction_service import base_result_snapshot

SCHEMA = 'hr12-archive-v2'
MAX_ITEMS = 5000
MAX_MANIFEST_BYTES = 8 * 1024 * 1024
_HASH = re.compile(r'^[0-9a-f]{64}$')


class ArchiveEvidenceError(ValueError):
    def __init__(self, code, message, status=409):
        self.code, self.message, self.status = code, message, status
        super().__init__(message)


def _fail(message, code='ASSESSMENT_ARCHIVE_INTEGRITY_INVALID'):
    raise ArchiveEvidenceError(code, message)


def json_copy(value):
    return json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                 separators=(',', ':'), default=str, allow_nan=False))


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':'), default=str, allow_nan=False).encode()).hexdigest()


def _same_hash(actual, expected):
    return isinstance(actual, str) and bool(_HASH.fullmatch(actual)) and hmac.compare_digest(actual, expected)


def result_at_version(result, version):
    """Validate only the immutable historical chain requested, not today's revision."""
    if not _same_hash(result.content_hash, result.calculate_content_hash()):
        _fail('正式考核结果指纹不一致，不能生成或回读可信档案。')
    if not _same_hash(result.calculation_hash, result.calculate_calculation_hash()):
        _fail('正式计算依据指纹不一致。')
    snap = json_copy(base_result_snapshot(result))
    seal = result.content_hash
    for rev in HrResultRevision.objects.filter(
        result_id=result.id, tenant_id=result.tenant_id,
        new_version__lte=version,
    ).order_by('new_version'):
        if (rev.previous_version != snap['version'] or rev.new_version != snap['version'] + 1
            or json_copy(rev.before_snapshot_json) != snap
            or not _same_hash(rev.content_hash, rev.calculate_content_hash())):
            _fail('历史结果更正链不完整或校验失败。')
        snap = json_copy(rev.after_snapshot_json)
        if snap.get('version') != rev.new_version or snap.get('sourceResultId') != str(result.id):
            _fail('历史结果版本关联不一致。')
        seal = rev.content_hash
    if snap.get('version') != version:
        _fail('指定结果版本不存在。')
    value = snap.get('calculatedScore')
    if value is not None:
        try:
            if isinstance(value, bool) or not Decimal(str(value)).is_finite():
                raise ValueError()
        except (ValueError, InvalidOperation):
            _fail('归档分数不是有限数值。')
    return snap, seal


def _fields(obj, names):
    return json_copy({name: getattr(obj, name) for name in names})


def credential_attachment_index(items, staff_id):
    """R11 attachment_index adapted to source-owned HR09 metadata snapshots.

    Validate teacher/credential/document membership; do not access live HR09
    records. Metadata without historical bytes is explicitly NOT byte-verified.
    """
    index, gaps = {}, []
    for item in items:
        if item.get('providerType') != 'qualification':
            continue
        q = item.get('snapshot')
        if not isinstance(q, dict):
            _fail('资质依据快照格式异常。')
        # Source-unavailable/status-only entries must never look like credentials.
        if 'credential_id' not in q:
            continue
        if q.get('staff_id') != str(staff_id):
            _fail('资质依据不属于本考核人员。')
        refs = q.get('document_refs', [])
        if not isinstance(refs, list) or any(not isinstance(ref, str) for ref in refs):
            _fail('资质文件引用格式异常。')
        if 'document_snapshots' not in q:
            if refs:
                gaps.append({'credentialId': q['credential_id'], 'status': 'LEGACY_REFERENCES_ONLY'})
            continue
        documents = q['document_snapshots']
        if not isinstance(documents, list) or len(documents) > MAX_ITEMS:
            _fail('资质附件版本清单异常。')
        for doc in documents:
            if (not isinstance(doc, dict) or not doc.get('documentId')
                or doc.get('credentialId') != q['credential_id']
                or not isinstance(doc.get('version'), int) or isinstance(doc.get('version'), bool)
                or doc['version'] < 1 or doc.get('fileRef') not in refs):
                _fail('附件与资质、人员或文件版本关联不一致。')
            key = doc['documentId']
            frozen = json_copy(doc)
            frozen['staffId'] = str(staff_id)
            frozen['credentialName'] = q.get('credential_name', '')
            frozen['verificationStatus'] = (
                'METADATA_FROZEN_BYTES_NOT_CHECKED'
                if isinstance(doc.get('sha256'), str) and _HASH.fullmatch(doc['sha256'])
                else 'CHECKSUM_NOT_CAPTURED'
            )
            if key in index and index[key] != frozen:
                _fail('相同附件编号存在冲突的历史版本。')
            index[key] = frozen
        captured_refs = {d.get('fileRef') for d in documents if isinstance(d, dict)}
        if set(refs) - captured_refs:
            gaps.append({'credentialId': q['credential_id'], 'status': 'PARTIAL_DOCUMENT_METADATA'})
    return list(index.values()), gaps


def freeze_result_context(case):
    """Bind the evidence at finalization, not at some later archive/read time.

    Previously finalized results are never modified. Historical/minimal cases
    without a full context keep an explicit gap and use legacy archive mode.
    Malformed existing context fails rather than silently taking that branch.
    """
    if not case.provider_snapshot_set_id:
        return {'status': 'NOT_CAPTURED', 'missing': ['providerSet']}
    subject = HrSubjectSnapshot.objects.select_for_update().filter(
        pk=case.subject_snapshot_id, tenant_id=case.tenant_id,
    ).first() if case.subject_snapshot_id else None
    cycle_snapshot = HrCycleSnapshot.objects.select_for_update().filter(
        tenant_id=case.tenant_id, cycle_id=case.cycle_id,
    ).first() if case.cycle_id else None
    sources = HrProviderSnapshotSet.objects.filter(
        id=case.provider_snapshot_set_id, tenant_id=case.tenant_id, case_id=case.id,
        status='READY', captured_at__isnull=False,
    ).first() if case.provider_snapshot_set_id else None
    if sources is None:
        _fail('已关联的来源快照不存在、跨学校或尚未就绪。')
    missing = [key for key, value in [('subject', subject), ('cycle', cycle_snapshot), ('providerSet', sources)] if value is None]
    if missing:
        return {'status': 'NOT_CAPTURED', 'missing': missing}
    if (not _HASH.fullmatch(sources.content_hash or '')
        or not isinstance(sources.provider_status_json, dict)
        or any(not isinstance(v, dict) or v.get('status') != 'OK' for v in sources.provider_status_json.values())):
        _fail('当期来源状态不完整。')
    if subject.case_id != case.id or subject.staff_id != case.staff_id or not str(subject.display_name or '').strip():
        _fail('当期人员快照的归属或姓名不完整。')
    if case.cycle.tenant_id != case.tenant_id or case.cycle.policy_version_id != case.policy_version_id:
        _fail('当期周期与学校或规则的关联不一致。')
    records = list(HrProviderSnapshotItem.objects.filter(snapshot_set=sources).order_by('provider_type', 'source_object_id', 'id')[:MAX_ITEMS+1])
    if len(records) > MAX_ITEMS:
        _fail('来源条目超过单份档案安全上限。')
    source_items = []
    for item in records:
        if (item.tenant_id != case.tenant_id or item.case_id != case.id
            or item.status != 'VERIFIED'
            or not _same_hash(item.snapshot_hash, item.calculate_snapshot_hash())):
            _fail('来源证据归属、状态或指纹校验失败。')
        source_items.append({
            'itemId': str(item.id), 'providerType': item.provider_type,
            'objectType': item.source_object_type, 'objectId': item.source_object_id,
            'sourceVersion': item.source_version,
            'sourceAsOf': item.source_as_of.isoformat() if item.source_as_of else None,
            'trustLevel': item.trust_level, 'status': item.status,
            'snapshotHash': item.snapshot_hash, 'snapshot': json_copy(item.snapshot_json),
        })
    required = set(sources.required_providers_json or [])
    if not required or required != {item['providerType'] for item in source_items}:
        _fail('来源快照成员与所需来源清单不一致。')
    attachments, gaps = credential_attachment_index(source_items, case.staff_id)
    frozen = {
        'status': 'COMPLETE', 'schemaVersion': 'hr12-finalization-evidence-v1',
        'caseId': str(case.id), 'staffId': str(case.staff_id),
        'subject': _fields(subject, ['id', 'case_id', 'staff_id', 'display_name', 'staff_code', 'org_id', 'org_name', 'position_id', 'position_name', 'worker_category', 'snapshot_at']),
        'cycle': {'id': str(case.cycle_id), 'nameAtFinalization': case.cycle.name,
                  'startAt': case.cycle.start_at.isoformat(), 'endAt': case.cycle.end_at.isoformat(),
                  'policyVersionId': str(case.policy_version_id),
                  'snapshot': _fields(cycle_snapshot, ['id', 'frozen_policy_json', 'frozen_rating_scale_json', 'frozen_indicator_set_json', 'frozen_workflow_json', 'frozen_reviewer_rules_json', 'frozen_at'])},
        'providerSet': _fields(sources, ['id', 'case_id', 'as_of', 'authority_json', 'required_providers_json', 'provider_status_json', 'content_hash', 'captured_at']),
        'providerItems': source_items, 'credentialAttachments': attachments,
        'attachmentGaps': gaps,
    }
    if len(json.dumps(frozen, ensure_ascii=False).encode()) > MAX_MANIFEST_BYTES:
        _fail('当期证据体积超过安全上限。')
    return frozen


@transaction.atomic
def capture_evidence(result, version):
    result_at_version(result, version)
    calculation = json_copy(result.calculation_snapshot_json or {})
    binding = calculation.get('evidenceBinding')
    if not isinstance(binding, dict) or binding.get('status') != 'COMPLETE':
        _fail('历史结果未冻结完整人员与规则依据，不得用当前记录补写。',
              'ASSESSMENT_ARCHIVE_CALCULATION_BINDING_REQUIRED')
    documents = []
    if result.decision_session_id:
        from hr_assessment.services.document_service import open_verified_document
        for doc in HrAssessmentDocument.objects.filter(
            tenant_id=result.tenant_id, related_object_type='DECISION_SESSION',
            related_object_id=result.decision_session_id, status='SEALED',
        ).order_by('id'):
            with open_verified_document(doc):
                pass
            documents.append(_fields(doc, ['id', 'document_type', 'original_filename', 'sha256', 'size_bytes', 'sealed_at']))
    # Deep copies ensure consumers cannot mutate the model's in-memory JSON.
    return {
        **deepcopy(binding), 'schemaVersion': 'hr12-evidence-v1',
        'calculation': calculation, 'calculationHash': result.calculation_hash,
        'decisionDocuments': documents,
        'boundary': 'HR09附件冻结版本元数据，未通过文件提供方核验字节；审定纪要在归档时核验字节。归档不是外部平台已接收。',
    }


def verified_archive(archive):
    """Return detached historical bytes-as-JSON, or fail closed. No repairs."""
    try:
        payload = archive.manifest_json
        if not isinstance(payload, dict) or len(json.dumps(payload, ensure_ascii=False).encode()) > MAX_MANIFEST_BYTES:
            _fail('归档清单格式或体积异常。')
        if (archive.archive_status != 'ARCHIVED' or not archive.sealed_at or not archive.archived_at
            or not _same_hash(archive.content_hash, digest(payload))
            or payload.get('tenantId') != archive.tenant_id
            or payload.get('resultId') != str(archive.result_id)
            or payload.get('resultVersion') != archive.result_version
            or payload.get('documentRefs') != archive.document_refs_json
            or archive.archive_provider_ref != f'hr12://archive/{archive.content_hash}'):
            _fail('归档清单与封存记录不一致，禁止可信查看或导出。')
        if payload.get('schemaVersion') not in {'hr12-archive-v1', SCHEMA}:
            _fail('不支持的历史归档格式，不能自动升级为可信档案。')
        result = archive.result
        if result is None or result.tenant_id != archive.tenant_id:
            _fail('归档结果不属于当前学校。')
        historical, seal = result_at_version(result, archive.result_version)
        if payload.get('canonicalResult') != historical or payload.get('resultContentHash') != seal:
            _fail('归档与指定版本的正式结果不一致。')
        if payload.get('schemaVersion') == SCHEMA:
            evidence = payload['evidence']
            subject = evidence['subject']
            if (evidence['caseId'] != str(result.case_id)
                or evidence['cycle']['id'] != str(result.cycle_id)
                or subject['case_id'] != str(result.case_id)
                or subject['staff_id'] != evidence['staffId']
                or not subject['display_name']
                or not _same_hash(evidence['calculationHash'], digest(evidence['calculation']))
                or evidence['calculationHash'] != result.calculation_hash
                or evidence['providerSet']['id'] != evidence['calculation'].get('providerSnapshotSetId')):
                _fail('归档人员、周期或计算依据不一致。')
            binding = evidence['calculation'].get('evidenceBinding')
            if not isinstance(binding, dict) or binding.get('status') != 'COMPLETE':
                _fail('计算时未冻结完整依据。')
            for key, value in binding.items():
                if key != 'schemaVersion' and evidence.get(key) != value:
                    _fail('归档上下文与审定时封存依据不同。')
            if (not isinstance(evidence['providerItems'], list)
                or len(evidence['providerItems']) > MAX_ITEMS):
                _fail('来源清单格式异常或超过安全上限。')
            seen = set()
            for item in evidence['providerItems']:
                if item['itemId'] in seen or not _same_hash(item['snapshotHash'], digest(item['snapshot'])):
                    _fail('归档来源条目重复或损坏。')
                seen.add(item['itemId'])
            attachments, gaps = credential_attachment_index(evidence['providerItems'], evidence['staffId'])
            if attachments != evidence['credentialAttachments'] or gaps != evidence['attachmentGaps']:
                _fail('归档附件版本清单与来源证据不一致。')
        return deepcopy(payload)
    except ArchiveEvidenceError:
        raise
    except (KeyError, ValueError, TypeError, AttributeError, InvalidOperation, OverflowError):
        _fail('归档证据缺失或损坏，禁止以当前数据自动补齐。')


def archive_projection(archive):
    """Least-data presentation: no unrestricted raw payload or storage URL exposure."""
    frozen = verified_archive(archive)
    evidence = frozen.get('evidence')
    base = {
        'archiveId': str(archive.id), 'archivePackageId': archive.archive_package_id,
        'resultId': str(archive.result_id), 'version': archive.result_version,
        'schemaVersion': frozen['schemaVersion'], 'contentHash': archive.content_hash,
        'archivedAt': archive.archived_at.isoformat(),
        'result': frozen['canonicalResult'], 'immutable': True,
        'identityFrozen': evidence is not None,
        'identityNote': '' if evidence else '旧归档未冻结身份、规则与附件细节；不使用当前记录补写历史。',
        'sources': [], 'attachments': [], 'calculation': {},
        'resultBasis': 'ORIGINAL_CALCULATION' if archive.result_version == 1 else 'CORRECTION_WITH_ORIGINAL_EVIDENCE',
        'correctionNote': '' if archive.result_version == 1 else '本版本包含正式更正；计算依据为原审定依据，不能将更正值声称为原公式重新计算结果。',
    }
    if evidence is not None:
        base.update(subject=evidence['subject'], cycle=evidence['cycle'],
                    calculation={k: v for k, v in evidence['calculation'].items() if k not in {'evidenceBinding', 'contributions'}},
                    attachmentGaps=evidence['attachmentGaps'], boundary=evidence['boundary'])
        base['cycle'] = {k: v for k, v in evidence['cycle'].items() if k != 'snapshot'}
        base['sources'] = [{k: x[k] for k in ('providerType','objectType','objectId','sourceVersion','sourceAsOf','status','snapshotHash')} for x in evidence['providerItems']]
        # File references/checksums are provenance, never public hyperlinks.
        base['attachments'] = [{k: x.get(k) for k in ('documentId','credentialId','credentialName','version','sha256','verificationStatus')} for x in evidence['credentialAttachments']]
        base['decisionDocuments'] = evidence['decisionDocuments']
    return base
