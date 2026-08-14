from hr_assessment.models.cycle import HrAssessmentCycle
from hr_assessment.models.evidence import HrReviewerAssignment
from hr_assessment.models.goal import HrAssessmentGoal


def _constraint_names(model):
    return {constraint.name for constraint in model._meta.constraints if constraint.name}


def test_hr12_stable_named_constraints_are_not_downgraded():
    assert "uniq_cycle_tenant_no_type" in _constraint_names(HrAssessmentCycle)
    assert "uniq_goal_tenant_code" in _constraint_names(HrAssessmentGoal)
    assert "uniq_reviewer_case_role" in _constraint_names(HrReviewerAssignment)
