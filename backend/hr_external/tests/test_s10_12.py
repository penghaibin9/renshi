"""S10/S11/S12 · Legacy 迁移分类 + 全量质量 + Authority 切换契约测试。

覆盖：
- S10 §116：迁移分类 CLEAR_EXTERNAL/POSSIBLE_EXTERNAL/REGULAR_EMPLOYEE/AMBIGUOUS；
- S12 §114：Authority 切换顺序 + 非法跳级阻断 + HR08_AUTHORITY 禁用 legacy 写；
- S11 基础：模型全部带 tenant_id 字段；索引存在；版本约束。
"""

from django.test import SimpleTestCase, TestCase

from hr_external.constants import ExternalAuthorityMode
from hr_external.models import (
    HrExternalAccessGrant,
    HrExternalAcademicIdentity,
    HrExternalAcademicProvisioningRequest,
    HrExternalCategory,
    HrExternalConflictDeclaration,
    HrExternalContribution,
    HrExternalEngagement,
    HrExternalEngagementAssignment,
    HrExternalEthicsReview,
    HrExternalExitCase,
    HrExternalHiringCase,
    HrExternalLifecycleEvent,
    HrExternalProjectionState,
    HrExternalProvisioningRequest,
    HrExternalRenewalReview,
    HrExternalServiceTask,
    HrExternalSettlementBasis,
    HrExternalTaskEvidence,
    HrExternalTeacherProfile,
    HrExternalWorkloadRecord,
    HrExternalWorkspace,
)
from hr_external.services.authority_service import (
    AuthorityService,
    AuthorityTransitionInvalid,
)
from hr_external.services.migration_service import MigrationClassificationService


class MigrationClassificationTests(SimpleTestCase):
    def setUp(self):
        self.service = MigrationClassificationService()

    def test_clear_external(self):
        c = self.service.classify(
            legacy_employee_id=1, employee_type_text="part-time", contract_name="兼职协议"
        )
        self.assertEqual(c.classification, "CLEAR_EXTERNAL")

    def test_possible_external(self):
        c = self.service.classify(
            legacy_employee_id=2, employee_type_text="其他", contract_name="产业教授协议"
        )
        self.assertEqual(c.classification, "POSSIBLE_EXTERNAL")

    def test_regular_employee(self):
        c = self.service.classify(
            legacy_employee_id=3, employee_type_text="正式在编", contract_name="事业单位聘用合同"
        )
        self.assertEqual(c.classification, "REGULAR_EMPLOYEE")

    def test_ambiguous(self):
        c = self.service.classify(legacy_employee_id=4)
        self.assertEqual(c.classification, "AMBIGUOUS")


class AuthoritySwitchTests(TestCase):
    def test_sequential_transition(self):
        svc = AuthorityService()
        self.assertEqual(svc.get_mode(101), ExternalAuthorityMode.LEGACY_EMPLOYEE_TAG_ONLY)
        svc.transition(tenant_id=101, target=ExternalAuthorityMode.DUAL_READ_COMPARE, actor_id=1)
        self.assertEqual(svc.get_mode(101), ExternalAuthorityMode.DUAL_READ_COMPARE)
        svc.transition(tenant_id=101, target=ExternalAuthorityMode.HR08_AUTHORITY, actor_id=1)
        self.assertEqual(svc.get_mode(101), ExternalAuthorityMode.HR08_AUTHORITY)
        self.assertFalse(svc.can_legacy_write(101))

    def test_illegal_skip_blocked(self):
        svc = AuthorityService()
        with self.assertRaises(AuthorityTransitionInvalid):
            svc.transition(tenant_id=102, target=ExternalAuthorityMode.HR08_AUTHORITY)

    def test_authority_blocks_legacy_write(self):
        svc = AuthorityService()
        svc.transition(tenant_id=103, target=ExternalAuthorityMode.DUAL_READ_COMPARE)
        svc.transition(tenant_id=103, target=ExternalAuthorityMode.HR08_AUTHORITY)
        self.assertFalse(svc.can_legacy_write(103))


class ModelGovernanceTests(TestCase):
    """S11 全量质量：所有权威模型必须带 tenant_id（A0 fail-closed DB 层，00 §8）。"""

    AUTHORITY_MODELS = [
        HrExternalCategory,
        HrExternalTeacherProfile,
        HrExternalEngagement,
        HrExternalEngagementAssignment,
        HrExternalHiringCase,
        HrExternalEthicsReview,
        HrExternalConflictDeclaration,
        HrExternalAccessGrant,
        HrExternalProvisioningRequest,
        HrExternalAcademicIdentity,
        HrExternalAcademicProvisioningRequest,
        HrExternalLifecycleEvent,
        HrExternalContribution,
        HrExternalWorkspace,
        HrExternalServiceTask,
        HrExternalTaskEvidence,
        HrExternalWorkloadRecord,
        HrExternalSettlementBasis,
        HrExternalRenewalReview,
        HrExternalExitCase,
        HrExternalProjectionState,
    ]

    def test_all_authority_models_have_tenant_id(self):
        for model in self.AUTHORITY_MODELS:
            fields = {f.name for f in model._meta.get_fields()}
            self.assertIn("tenant_id", fields, f"{model.__name__} missing tenant_id")
            field = model._meta.get_field("tenant_id")
            self.assertTrue(field.db_index, f"{model.__name__}.tenant_id should be indexed")

    def test_category_has_version_check_constraint(self):
        # 版本约束（§118 version>=1）—— 用 CheckConstraint 校验
        from django.db.models import CheckConstraint

        self.assertTrue(
            any(
                isinstance(c, CheckConstraint)
                and "version" in str(c.condition)
                for c in HrExternalCategory._meta.constraints
            )
        )

    def test_all_models_have_version_gte_1_check(self):
        from django.db.models import CheckConstraint

        for model in self.AUTHORITY_MODELS:
            has_check = any(
                isinstance(c, CheckConstraint) and "version" in str(c.condition)
                for c in model._meta.constraints
            )
            self.assertTrue(has_check, f"{model.__name__} missing version>=1 CheckConstraint")
