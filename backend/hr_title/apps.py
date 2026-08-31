from django.apps import AppConfig
from django.db.models.signals import post_migrate


def _restore_result_permission(*, using, **_kwargs):
    """Recreate the formal HR13 result permission after flush/post_migrate."""
    from django.contrib.auth.models import Permission
    from django.contrib.contenttypes.models import ContentType

    from .models import TitleApplicationCase

    content_type = ContentType.objects.db_manager(using).get_for_model(
        TitleApplicationCase,
        for_concrete_model=False,
    )
    for codename, name in (
        ("hr.title.result", "发布 HR13 正式职称结果"),
        ("hr.title.result.correct", "修订与撤销 HR13 已封板正式职称结果"),
    ):
        Permission.objects.using(using).get_or_create(
            content_type=content_type,
            codename=codename,
            defaults={"name": name},
        )


class HrTitleConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "hr_title"
    verbose_name = "HR13 职称评审"

    def ready(self):
        # Import-only canonical registration. No database query or mutation is
        # performed here; the global gate can therefore verify HR13 at startup.
        from . import authority_registry  # noqa: F401

        # 0007 originally introduced this permission through RunPython only.
        # Django flush removes that data row and does not replay data migrations;
        # restore it on post_migrate so isolated/full-suite databases keep the
        # same permission contract as a freshly migrated production database.
        post_migrate.connect(
            _restore_result_permission,
            sender=self,
            dispatch_uid="hr_title.restore_result_permission",
        )
