from django.apps import AppConfig
from django.db.models.signals import post_migrate


def _restore_workflow_permissions(*, using, **_kwargs):
    """Recreate HR14 workflow permissions after flush/post_migrate."""
    from django.contrib.auth.models import Permission
    from django.contrib.contenttypes.models import ContentType

    from .models import AppointmentPolicyVersion

    content_type = ContentType.objects.db_manager(using).get_for_model(
        AppointmentPolicyVersion,
        for_concrete_model=False,
    )
    for codename, name in (
        ("hr.appointment.application", "办理 HR14 岗位竞聘申报"),
        ("hr.appointment.manage", "管理 HR14 竞聘批次与资格审查"),
    ):
        Permission.objects.using(using).get_or_create(
            content_type=content_type,
            codename=codename,
            defaults={"name": name},
        )


class HrAppointmentConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "hr_appointment"
    verbose_name = "HR14 岗位聘任"

    def ready(self):
        # Large authority subdomains stay split into focused model modules.
        # Importing here registers model classes and runtime immutability guards;
        # it performs no database queries or startup writes.
        from . import (  # noqa: F401
            decision_models,
            freeze_guards,
            population_models,
            term_models,
        )

        # 0012 introduced these permissions through RunPython only. A Django
        # flush removes those rows without replaying data migrations, so restore
        # them only on post_migrate; this remains idempotent and database-aware.
        post_migrate.connect(
            _restore_workflow_permissions,
            sender=self,
            dispatch_uid="hr_appointment.restore_workflow_permissions",
        )
