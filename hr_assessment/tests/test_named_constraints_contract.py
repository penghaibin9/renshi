from django.test import SimpleTestCase

from hr_assessment.models.cycle import HrAssessmentCycle
from hr_assessment.models.evidence import HrReviewerAssignment
from hr_assessment.models.goal import HrAssessmentGoal


def _constraint_names(model):
    return {constraint.name for constraint in model._meta.constraints if constraint.name}


class Hr12NamedConstraintContractTests(SimpleTestCase):
    def test_hr12_stable_named_constraints_are_not_downgraded(self):
        self.assertIn(
            "uniq_cycle_tenant_no_type", _constraint_names(HrAssessmentCycle)
        )
        self.assertIn("uniq_goal_tenant_code", _constraint_names(HrAssessmentGoal))
        self.assertIn(
            "uniq_reviewer_case_role", _constraint_names(HrReviewerAssignment)
        )
