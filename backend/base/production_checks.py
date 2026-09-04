"""Repository-specific production database contract checks."""

from django.apps import apps
from django.conf import settings
from django.core.checks import Error, Tags, register
from django.db.models import UniqueConstraint


# These constraints are implemented on MySQL by fail-loud migrations that add
# generated guard columns and unique indexes. Keeping the exact allow-list here
# means a future conditional constraint cannot be hidden by models.W036 unless
# its physical MySQL enforcement is added at the same time.
MYSQL_CONDITIONAL_UNIQUE_BACKSTOPS = frozenset(
    {
        ("hr_control_center.HrAlertInstance", "uniq_hr_alert_open_dedupe"),
        ("hr_external.HrExternalExitCase", "uniq_hr_external_active_exit_per_eng"),
        (
            "hr_recruitment.HrJobApplication",
            "uniq_hr_application_active_per_position",
        ),
        ("hr_recruitment.HrJobApplication", "uniq_hr_application_no_tenant"),
        (
            "hr_staff.HrPersonIdentityDocument",
            "uniq_hr_identity_fingerprint_tenant",
        ),
        (
            "hr_staff.HrStaffAssignment",
            "uniq_hr_assignment_open_primary_per_rel",
        ),
    }
)


def conditional_unique_constraints():
    return {
        (model._meta.label, constraint.name)
        for model in apps.get_models()
        for constraint in model._meta.constraints
        if isinstance(constraint, UniqueConstraint) and constraint.condition is not None
    }


@register(Tags.models)
def mysql_conditional_uniqueness_backstops(app_configs=None, **kwargs):
    engine = settings.DATABASES.get("default", {}).get("ENGINE", "")
    if engine != "django.db.backends.mysql":
        return []

    missing = conditional_unique_constraints() - MYSQL_CONDITIONAL_UNIQUE_BACKSTOPS
    return [
        Error(
            "MySQL has no physical backstop registered for conditional unique "
            f"constraint {model_label}.{constraint_name}.",
            hint=(
                "Add a fail-loud generated-column unique-index migration and then "
                "register the exact model/constraint pair in "
                "base.production_checks.MYSQL_CONDITIONAL_UNIQUE_BACKSTOPS."
            ),
            id="horilla.E001",
        )
        for model_label, constraint_name in sorted(missing)
    ]
