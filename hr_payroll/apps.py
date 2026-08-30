from django.apps import AppConfig


class HrPayrollConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "hr_payroll"
    verbose_name = "HR15 薪酬福利"

    def ready(self):
        from . import (  # noqa: F401
            authority_models,
            authority_registry,
            calculation_models,
            legacy_takeover_models,
            statutory_models,
        )
        from django.db.models.signals import m2m_changed

        from payroll.models.models import Payslip

        from .services.legacy_takeover_service import (
            execute_guarded_legacy_payslip_write,
        )

        def _seal_legacy_installments(sender, instance, action, **kwargs):
            if action not in {"pre_add", "pre_remove", "pre_clear"}:
                return
            tenant_id = getattr(
                getattr(instance.employee_id, "employee_work_info", None),
                "company_id_id",
                None,
            )
            execute_guarded_legacy_payslip_write(
                tenant_ids={tenant_id},
                operation="M2M_" + action[4:].upper(),
                object_refs=[instance.pk],
                write=lambda: None,
            )

        m2m_changed.connect(
            _seal_legacy_installments,
            sender=Payslip.installment_ids.through,
            dispatch_uid="hr15.seal_legacy_payslip_installments",
            weak=False,
        )
