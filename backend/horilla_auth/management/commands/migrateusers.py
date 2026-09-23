from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction, connection
from django.utils import timezone
from horilla_auth.legacy_identity import migration_action, LegacyIdentityConflict, SECURITY_FIELDS
from base.models import SchoolBootstrapState

from horilla_auth.models import (
    AuthUserGroups,
    AuthUserUserPermissions,
    HorillaUser,
    LegacyUser,
)


class Command(BaseCommand):
    help = "Migrate users from LegacyUser (auth_user) to HorillaUser, including groups and permissions."

    def handle(self, *args, **options):
        tables = set(connection.introspection.table_names())
        if "auth_user" not in tables:
            self.stdout.write("LEGACY_USERS_NOT_PRESENT：全新安装无需旧账号迁移，未创建或更改账号。")
            return
        if not LegacyUser.objects.exists():
            self.stdout.write("LEGACY_USERS_EMPTY：没有待迁移旧账号。")
            return
        if not {"auth_user_groups", "auth_user_user_permissions"}.issubset(tables):
            raise CommandError("旧账号授权表不完整，拒绝猜测或丢弃原权限；请先核对迁移来源。")
        created_count = 0
        skipped_count = 0

        with transaction.atomic():
            SchoolBootstrapState.objects.get_or_create(pk=1)
            SchoolBootstrapState.objects.select_for_update().get(pk=1)
            # Freeze existing rows and preflight all identities before any create.
            old_users = list(LegacyUser.objects.select_for_update().order_by("id"))
            targets = list(HorillaUser.objects.select_for_update().all())
            fields = ("id", "username", *SECURITY_FIELDS)
            snapshot = lambda user: {key: getattr(user, key) for key in fields}
            by_id = {user.id: snapshot(user) for user in targets}
            by_name = {user.username.casefold(): snapshot(user) for user in targets}
            plans = []
            for old in old_users:
                try:
                    action = migration_action(snapshot(old), by_id.get(old.id), by_name.get(old.username.casefold()))
                except LegacyIdentityConflict as exc:
                    raise CommandError(f"旧账号编号 {old.id}：{exc}") from exc
                groups = set(AuthUserGroups.objects.filter(user_id=old.id).values_list("group_id", flat=True))
                perms = set(AuthUserUserPermissions.objects.filter(user_id=old.id).values_list("permission_id", flat=True))
                if Group.objects.filter(pk__in=groups).count() != len(groups) or Permission.objects.filter(pk__in=perms).count() != len(perms):
                    raise CommandError(f"旧账号编号 {old.id} 存在无效权限引用；整批迁移已取消。")
                if action == "EXACT_EXISTING":
                    target = HorillaUser.objects.get(pk=old.id)
                    if set(target.groups.values_list("id", flat=True)) != groups or set(target.user_permissions.values_list("id", flat=True)) != perms:
                        raise CommandError(f"旧账号编号 {old.id} 的当前权限与旧权限不同；不会覆盖当前权限。")
                plans.append((old, action))
            for old_user, action in plans:
                if action == "EXACT_EXISTING":
                    skipped_count += 1
                    continue

                date_joined = old_user.date_joined
                if date_joined and timezone.is_naive(date_joined):
                    date_joined = timezone.make_aware(date_joined)
                last_login = old_user.last_login
                if last_login and timezone.is_naive(last_login):
                    last_login = timezone.make_aware(last_login)

                new_user = HorillaUser.objects.create(
                    id=old_user.id,
                    username=old_user.username,
                    password=old_user.password,
                    first_name=old_user.first_name,
                    last_name=old_user.last_name,
                    email=old_user.email,
                    is_staff=old_user.is_staff,
                    is_active=old_user.is_active,
                    is_superuser=old_user.is_superuser,
                    last_login=last_login,
                    date_joined=date_joined,
                    is_new_employee=False,
                )

                group_ids = AuthUserGroups.objects.filter(
                    user_id=old_user.id
                ).values_list("group_id", flat=True)
                new_user.groups.set(Group.objects.filter(id__in=group_ids))

                permission_ids = AuthUserUserPermissions.objects.filter(
                    user_id=old_user.id
                ).values_list("permission_id", flat=True)
                new_user.user_permissions.set(
                    Permission.objects.filter(id__in=permission_ids)
                )

                created_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"✅ Migration complete: {created_count} users migrated, {skipped_count} already matched; existing credentials and permissions were not overwritten."
            )
        )
