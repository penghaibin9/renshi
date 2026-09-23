"""Safely bootstrap the first production company and administrator.

This command is deliberately separate from ``prepare_runtime``.  Database schema
preparation must never create a privileged identity implicitly.  The operator
runs this once after the release container has completed successfully.
"""

from __future__ import annotations

import os

from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email
from django.db import transaction

from base.models import Company, SchoolBootstrapState
from base.first_use_policy import normalize_bootstrap_options, BootstrapInputError
from horilla.horilla_middlewares import tenant_context
from django.utils import timezone
from employee.models import Employee
from horilla_auth.models import HorillaUser


PASSWORD_ENV = "HR_BOOTSTRAP_ADMIN_PASSWORD"
BOT_USERNAME = "Horilla Bot"


class Command(BaseCommand):
    help = (
        "Create the first production company, superuser and linked employee. "
        f"The password is read only from {PASSWORD_ENV}; it is never accepted "
        "as a command-line argument."
    )

    def add_arguments(self, parser):
        parser.add_argument("--username", default="", help="Optional; defaults to the administrator email.")
        parser.add_argument("--email", required=True)
        parser.add_argument("--first-name", "--admin-name", dest="first_name", required=True)
        parser.add_argument("--last-name", default="")
        parser.add_argument("--phone", default="", help="Optional; can be completed later.")
        parser.add_argument("--company-name", "--school-name", dest="company_name", required=True)
        parser.add_argument("--company-address", default="", help="Optional; can be completed later.")
        parser.add_argument("--company-country", default="", help="Optional; can be completed later.")
        parser.add_argument("--company-state", default="", help="Optional; can be completed later.")
        parser.add_argument("--company-city", default="", help="Optional; can be completed later.")
        parser.add_argument("--company-zip", default="", help="Optional; can be completed later.")
        parser.add_argument(
            "--allow-non-production",
            action="store_true",
            help="Test/development escape hatch. Never use for a real deployment.",
        )

    @staticmethod
    def _required(value, label):
        value = str(value or "").strip()
        if not value:
            raise CommandError(f"{label} must not be blank")
        return value

    def _validate_options(self, options):
        try:
            values = normalize_bootstrap_options(options)
        except BootstrapInputError as exc:
            raise CommandError(str(exc)) from exc
        try:
            validate_email(values["email"])
        except ValidationError as exc:
            raise CommandError("email is not a valid email address") from exc
        return values

    @staticmethod
    def _company_matches(company, values):
        expected = {
            "company": values["company_name"],
            "address": values["company_address"],
            "country": values["company_country"],
            "state": values["company_state"],
            "city": values["company_city"],
            "zip": values["company_zip"],
        }
        return company.hq and all(
            getattr(company, key) == value
            for key, value in expected.items()
            if key == "company" or value  # omitted optional fields never erase later profile edits
        )

    def _already_complete(self, values, password):
        """Return True only when this exact bootstrap has already completed."""
        user = HorillaUser.objects.filter(username=values["username"]).first()
        company = Company.objects.filter(
            company=values["company_name"]
        ).first()
        if not user or not company:
            return False
        if not (user.is_superuser and user.is_staff and user.is_active):
            return False
        if not user.check_password(password):
            return False
        if user.email != values["email"]:
            return False
        try:
            employee = user.employee_get
            work_info = employee.employee_work_info
        except (ObjectDoesNotExist, AttributeError):
            return False
        return (
            employee.employee_first_name == values["first_name"]
            and (employee.employee_last_name or "") == values["last_name"]
            and employee.email == values["email"]
            and (not values["phone"] or employee.phone == values["phone"])
            and work_info.company_id_id == company.id
            and self._company_matches(company, values)
        )

    def _assert_clean_or_exact_rerun(self, values, password):
        if Company.objects.count() == 1 and self._already_complete(values, password):
            return True

        # A partially initialised database is deliberately not repaired here.
        # An operator must inspect it rather than risk attaching a new superuser
        # to pre-existing HR data.
        existing_non_bot_user = HorillaUser.objects.exclude(username=BOT_USERNAME).exists()
        if existing_non_bot_user or Company.objects.exists() or Employee.objects.entire().exists():
            raise CommandError(
                "Database is not empty and does not exactly match this bootstrap request. "
                "Refusing to create or attach a privileged account."
            )
        return False

    def handle(self, *args, **options):
        if not getattr(settings, "IS_PRODUCTION", False) and not options[
            "allow_non_production"
        ]:
            raise CommandError(
                "bootstrap_production_admin is production-only; refusing to run."
            )

        values = self._validate_options(options)
        password = os.environ.get(PASSWORD_ENV, "")
        if not password:
            raise CommandError(
                f"{PASSWORD_ENV} is required. Export it temporarily; do not put the "
                "password in shell arguments or source-controlled .env files."
            )

        candidate = HorillaUser(
            username=values["username"],
            email=values["email"],
            first_name=values["first_name"],
            last_name=values["last_name"],
        )
        try:
            validate_password(password, user=candidate)
        except ValidationError as exc:
            raise CommandError("Bootstrap administrator password is too weak: " + "; ".join(exc.messages)) from exc

        try:
            candidate.full_clean(exclude=["password"], validate_unique=False)
        except ValidationError as exc:
            raise CommandError("管理员账号资料不符合规则，请核对姓名、邮箱和登录账号。") from exc

        with transaction.atomic():
            # Both callers must lock the SAME existing row, even on an empty DB.
            # An empty Company select_for_update() cannot serialize first signup.
            SchoolBootstrapState.objects.get_or_create(pk=1)
            bootstrap = SchoolBootstrapState.objects.select_for_update().get(pk=1)
            if self._assert_clean_or_exact_rerun(values, password):
                self.stdout.write(self.style.SUCCESS("PRODUCTION_BOOTSTRAP_ALREADY_COMPLETE"))
                return

            company = Company(
                company=values["company_name"],
                hq=True,
                address=values["company_address"],
                country=values["company_country"],
                state=values["company_state"],
                city=values["company_city"],
                zip=values["company_zip"],
            )
            company.full_clean()
            company.save()

            user = HorillaUser.objects.create_superuser(
                username=values["username"],
                email=values["email"],
                password=password,
                first_name=values["first_name"],
                last_name=values["last_name"],
            )

            employee = Employee(
                employee_user_id=user,
                employee_first_name=values["first_name"],
                employee_last_name=values["last_name"],
                email=values["email"],
                phone=values["phone"],
                gender=None,
                marital_status=None,
            )
            with tenant_context(company.pk):
                employee.save()
                work_info = employee.employee_work_info
                work_info.company_id = company
                work_info.email = values["email"]
                work_info.mobile = values["phone"]
                work_info.save()
                # Force database readback before completing the receipt.
                employee.refresh_from_db()
                work_info.refresh_from_db()
                if employee.employee_user_id_id != user.pk or work_info.company_id_id != company.pk:
                    raise CommandError("管理员与学校关联校验失败，开户事务已取消。")

            bootstrap.company = company
            bootstrap.administrator = user
            bootstrap.completed_at = timezone.now()
            bootstrap.save(update_fields=["company", "administrator", "completed_at"])

            bot, created = HorillaUser.objects.get_or_create(username=BOT_USERNAME)
            if created:
                bot.is_active = False
                bot.set_unusable_password()
                bot.save(update_fields=["password", "is_active"])

        self.stdout.write(self.style.SUCCESS("PRODUCTION_BOOTSTRAP_COMPLETE"))
        self.stdout.write("学校和首位管理员已创建。登录后打开 /settings/system-management/ 按下一步办理。")
        self.stdout.write("地址、国家、省市、邮编和电话未填时保持空白，可在学校资料中后补。")
        self.stdout.write("这仅代表开户完成，不代表工资、合同或生产部署验收通过。")
        self.stdout.write(
            self.style.WARNING(
                f"Unset {PASSWORD_ENV} now. The password was not written by this command."
            )
        )
