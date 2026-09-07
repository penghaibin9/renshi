"""Create the initial platform operator without manufacturing personnel facts.

The credential secret is read only from ``PLATFORM_INITIAL_ADMIN_PASSWORD`` so
it does not need to appear in shell history or the process argument list. This
command intentionally creates no Employee, school membership, HR03 StaffMaster
or tenant elevation: those are separate authorities and workflows.
"""

from __future__ import annotations

import os

from auditlog.models import LogEntry
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError, transaction

from platform_access.services import is_platform_operator

PASSWORD_ENV = "PLATFORM_INITIAL_ADMIN_PASSWORD"


class Command(BaseCommand):
    help = "Create an unbound platform operator using a password supplied by environment."

    def add_arguments(self, parser):
        parser.add_argument("--username", required=True)
        parser.add_argument("--email", required=True)

    def _secret(self) -> str:
        value = os.environ.get(PASSWORD_ENV, "")
        if not value:
            raise CommandError(
                f"{PASSWORD_ENV} must be set; plaintext password command arguments are not supported."
            )
        return value

    def _existing_is_idempotent(self, user) -> bool:
        if user is None:
            return False
        if not is_platform_operator(user):
            raise CommandError(
                "The username already belongs to an Employee, school account, or other non-platform identity."
            )
        self.stdout.write(
            self.style.WARNING(
                "Platform operator already exists; credentials and account state were left unchanged."
            )
        )
        return True

    def handle(self, *args, **options):
        username = str(options["username"] or "").strip()
        email = str(options["email"] or "").strip()
        if not username:
            raise CommandError("--username must not be blank")
        if not email:
            raise CommandError("--email must not be blank")

        password = self._secret()
        User = get_user_model()

        candidate = User(
            username=username,
            email=email,
            is_active=True,
            is_staff=True,
            is_superuser=True,
            # Reuse the existing first-password gate. This flag does not imply
            # an Employee row and is cleared only by the account-owned password flow.
            is_new_employee=True,
        )
        try:
            validate_password(password, candidate)
        except ValidationError as exc:
            raise CommandError("Initial platform password rejected: " + " ".join(exc.messages)) from exc

        try:
            with transaction.atomic():
                existing = User.objects.select_for_update().filter(username=username).first()
                if self._existing_is_idempotent(existing):
                    return

                email_owner = User.objects.select_for_update().filter(email__iexact=email).first()
                if email_owner is not None:
                    raise CommandError("The email address already belongs to another account.")

                candidate.set_password(password)
                candidate.save()
                if not is_platform_operator(candidate):
                    raise CommandError("Created account did not satisfy the platform-operator boundary.")

                # Do not serialize the User object: the password hash is sensitive.
                LogEntry.objects.log_create(
                    candidate,
                    action=LogEntry.Action.CREATE,
                    changes={"platform_operator": [None, True]},
                    actor=None,
                    serialized_data=None,
                    additional_data={"source": "createplatformoperator"},
                )
        except IntegrityError as exc:
            # Concurrent first creation is resolved by the username uniqueness
            # constraint. Re-read only after the failed transaction is closed.
            existing = User.objects.filter(username=username).first()
            if self._existing_is_idempotent(existing):
                return
            raise CommandError("Platform operator creation conflicted with another account write.") from exc

        self.stdout.write(
            self.style.SUCCESS(
                "Platform operator created without Employee or school membership; first password change is required."
            )
        )
