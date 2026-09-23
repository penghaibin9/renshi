"""Explicit read-only MySQL content snapshot; never restores or changes data."""
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from hr_onboarding.services.delivery_snapshot import capture_models
from hr_onboarding.services.delivery_evidence_io import read_private_key, validate_new_json_path, write_new_private_json


class Command(BaseCommand):
    help = "Export a keyed, non-PII first-delivery proof from MySQL; not an acceptance certificate."
    def add_arguments(self,parser):
        parser.add_argument("--school-id",type=int,required=True)
        parser.add_argument("--key-file",type=Path,required=True)
        parser.add_argument("--output",type=Path,required=True)
        parser.add_argument("--confirm-quiesced",action="store_true",help="acknowledge consistent maintenance/backup point")
    def handle(self,*args,**options):
        from django.conf import settings
        if not options["confirm_quiesced"]: raise CommandError("Confirm the maintenance/backup point before collecting evidence")
        if connection.vendor!="mysql": raise CommandError("MYSQL_REQUIRED: SQLite is not restore evidence")
        if connection.in_atomic_block: raise CommandError("Run snapshot outside an existing transaction")
        key_file=options["key_file"]; output=options["output"]
        try:
            key = read_private_key(key_file)
            output = validate_new_json_path(output)
        except (ValueError, OSError) as exc:
            raise CommandError("Key or output path rejected: " + str(exc)) from exc
        resolved=output.resolve()
        for name in ("MEDIA_ROOT","STATIC_ROOT"):
            value=getattr(settings,name,None)
            if value and resolved.is_relative_to(Path(value).resolve()): raise CommandError("Proof files cannot be placed in web/media storage")
        if options["school_id"]<=0: raise CommandError("School ID must be positive")
        from base.models import Company
        if not Company.objects.filter(pk=options["school_id"]).exists(): raise CommandError("School does not exist")
        with connection.cursor() as cursor:
            cursor.execute("SELECT VERSION()")
            version=str(cursor.fetchone()[0])
            if not version.startswith("8.4."): raise CommandError("Use the MySQL 8.4 acceptance release line")
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        with transaction.atomic():
            proof=capture_models(options["school_id"],key)
        proof.update(database_vendor=connection.vendor,database_version=version,
            database_name=str(connection.settings_dict["NAME"]),writes_performed=False,release_approved=False)
        try:
            write_new_private_json(output, proof)
        except (ValueError, OSError) as exc:
            raise CommandError("Evidence was not published; preserve existing files and retry with a new path") from exc
        self.stdout.write("SNAPSHOT_WRITTEN; NOT_RESTORE_OR_CUSTOMER_ACCEPTANCE")
