"""Source contracts for the first-use HR03 readiness gate; not MySQL acceptance."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = (ROOT / 'backend/base/first_use.py').read_text(encoding='utf-8')
MYSQL_TEST = (ROOT / 'backend/hr_staff/tests/test_minimal_import_mysql.py').read_text(encoding='utf-8')


def test_first_use_no_longer_counts_bare_staff_master():
    assert 'HrStaffMaster.objects.filter(tenant_id=school.pk).exists()' not in SOURCE
    assert '_has_complete_hr03_staff_authority(school.pk)' in SOURCE


def test_first_use_requires_one_current_coherent_authority_chain():
    assert 'person_id__tenant_id=tenant_id' in SOURCE
    assert 'HrEmploymentRelationship.objects.filter(' in SOURCE
    assert 'staff_id=OuterRef("pk")' in SOURCE
    assert 'HrStaffAssignment.objects.filter(' in SOURCE
    assert 'employment_relationship_id=OuterRef("pk")' in SOURCE
    assert 'effective_from__lte=today' in SOURCE
    assert 'Q(effective_to__isnull=True) | Q(effective_to__gt=today)' in SOURCE
    assert 'Exists(assignment_qs)' in SOURCE
    assert 'Exists(relationship_qs)' in SOURCE


def test_hr02_authority_cutover_disallows_legacy_only_readiness():
    assert 'get_mode(tenant_id) == "HR02_AUTHORITY"' in SOURCE
    assert 'organization_id__tenant_id=tenant_id' in SOURCE


def test_real_mysql_suite_covers_complete_and_broken_chain():
    assert 'test_first_use_readiness_requires_complete_four_layer_authority' in MYSQL_TEST
    assert 'test_half_staff_master_never_marks_first_use_staff_ready' in MYSQL_TEST
