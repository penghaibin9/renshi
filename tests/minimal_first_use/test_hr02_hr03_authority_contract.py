"""Static contracts for HR02 organization -> HR03 assignment integrity.

These assertions protect the implementation shape only.  They are deliberately
not reported as real-MySQL acceptance.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
IMPORT_VALIDATION = (ROOT / 'backend/hr_staff/services/import_validation.py').read_text(encoding='utf-8')
IMPORT_SERVICE = (ROOT / 'backend/hr_staff/services/import_service.py').read_text(encoding='utf-8')
ASSIGNMENT_SERVICE = (ROOT / 'backend/hr_staff/services/assignment_service.py').read_text(encoding='utf-8')
ASSIGNMENT_POLICY = (ROOT / 'backend/hr_staff/policies/assignment_policy.py').read_text(encoding='utf-8')


def test_import_preview_and_commit_share_hr02_department_mapping_rule():
    assert 'resolve_hr02_organization_for_department(' in IMPORT_VALIDATION
    assert 'for_update=True' in IMPORT_VALIDATION
    assert '本校已启用 HR02 权威组织' in IMPORT_VALIDATION
    assert 'legacy_model="department"' in IMPORT_VALIDATION
    assert 'link_status="MAPPED"' in IMPORT_VALIDATION


def test_import_writes_and_reads_back_hr02_org_when_mapping_exists():
    assert 'hr02_organization_id = row_data.get("_hr02_organization_id")' in IMPORT_SERVICE
    assert 'organization_id=hr02_organization_id' in IMPORT_SERVICE
    assert 'organization_id_id=hr02_organization_id' in IMPORT_SERVICE
    assert 'legacy_department_id=legacy_dept' in IMPORT_SERVICE


def test_assignment_locks_current_relationship_and_authority_refs():
    assert 'select_for_update()' in ASSIGNMENT_SERVICE
    assert '_lock_authority_refs(' in ASSIGNMENT_SERVICE
    assert 'CROSS_TENANT_REFERENCE' in ASSIGNMENT_SERVICE


def test_assignment_enforces_relationship_org_position_and_total_fte():
    assert 'validate_relationship_window(' in ASSIGNMENT_SERVICE
    assert 'validate_org_position_as_of(' in ASSIGNMENT_SERVICE
    assert 'validate_total_fte(' in ASSIGNMENT_SERVICE
    assert 'POSITION_ORG_MISMATCH' in ASSIGNMENT_POLICY
    assert 'POSITION_NOT_ASSIGNABLE' in ASSIGNMENT_POLICY
    assert 'ASSIGNMENT_OUTSIDE_RELATIONSHIP' in ASSIGNMENT_POLICY
    assert 'FTE_POLICY_EXCEEDED' in ASSIGNMENT_POLICY
