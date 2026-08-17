from django.test import TestCase, override_settings

from base.models import Company, Department
from horilla.horilla_middlewares import get_selected_company, tenant_context


@override_settings(TENANT_FAIL_CLOSED=True, TENANT_INCLUDE_GLOBAL_NULL_ROWS=False)
class TenantFailClosedTests(TestCase):
    """H0/A0 negative tests: no tenant and cross-tenant reads must return nothing."""

    def setUp(self):
        self.school_a = Company.objects.create(
            company="School A",
            address="A road",
            country="CN",
            state="HN",
            city="Changsha",
            zip="410000",
            hq=True,
        )
        self.school_b = Company.objects.create(
            company="School B",
            address="B road",
            country="CN",
            state="HN",
            city="Zhuzhou",
            zip="412000",
        )
        self.dept_a = Department.objects.entire().create(department="A Department")
        self.dept_a.company_id.add(self.school_a)
        self.dept_b = Department.objects.entire().create(department="B Department")
        self.dept_b.company_id.add(self.school_b)

    def test_no_tenant_context_returns_empty_queryset(self):
        self.assertIsNone(get_selected_company())
        self.assertFalse(Department.objects.exists())

    def test_concrete_tenant_cannot_read_other_school(self):
        with tenant_context(self.school_a.id):
            self.assertEqual(
                list(Department.objects.values_list("department", flat=True)),
                ["A Department"],
            )

    def test_context_is_restored_after_job_scope(self):
        self.assertIsNone(get_selected_company())
        with tenant_context(self.school_b.id):
            self.assertEqual(get_selected_company(), self.school_b.id)
        self.assertIsNone(get_selected_company())

    def test_tenant_context_rejects_all_or_missing(self):
        with self.assertRaises(ValueError):
            with tenant_context(None):
                pass
        with self.assertRaises(ValueError):
            with tenant_context("all"):
                pass
