"""Real file/crypto tests; MySQL execution is deliberately mocked and not claimed."""
import io, json, os, tarfile, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from django.conf import settings
if not settings.configured:
    settings.configure(DEFAULT_CHARSET="utf-8", INSTALLED_APPS=[])
from django.test import override_settings
from django.core.management.base import CommandError
from horilla_backup import handover as h
from horilla_backup import production as p
from horilla_backup.management.commands import restore_production_backup as dr
from horilla_backup.management.commands import restore_school_handover_package as school
from horilla_backup.management.commands import verify_production_backup as verify

class BackupCloseoutTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.bundle=self.root/"backups"/"bundle"
        self.bundle.mkdir(parents=True);self.media=self.root/"live-media";self.media.mkdir()
        self.options=override_settings(MEDIA_ROOT=str(self.media),STATIC_ROOT=str(self.root/"static"),
            REPO_ROOT=str(self.root/"repo"),PRODUCTION_BACKUP_ROOT=str(self.root/"backups"),
            SCHOOL_HANDOVER_ROOT=str(self.root/"handover"),SCHOOL_HANDOVER_RECEIPT_ROOT=str(self.root/"receipts"),
            PRODUCTION_BACKUP_ENCRYPTION_KEY="test-only-"*8,DATABASES={"default":{"NAME":"live_db"}})
        self.options.enable();self.addCleanup(self.options.disable)
    def archive(self, entries=None):
        path=self.root/"input.tar.gz"
        entries=entries if entries is not None else [(".",tarfile.DIRTYPE,b""),("./folder/a.txt",tarfile.REGTYPE,b"payload")]
        with tarfile.open(path,"w:gz") as out:
            for name, kind, body in entries:
                item=tarfile.TarInfo(name);item.type=kind;item.size=len(body) if kind==tarfile.REGTYPE else 0
                if kind in (tarfile.SYMTYPE,tarfile.LNKTYPE):item.linkname="../escaped"
                out.addfile(item,io.BytesIO(body) if kind==tarfile.REGTYPE else None)
        return path
    def make_bundle(self, entries=None):
        sql=self.root/"sql";sql.write_bytes(b"CREATE TABLE controlled_test (id INTEGER);\n")
        media=self.archive(entries)
        files={"database.sql.enc":sql,"media.tar.gz.enc":media}
        manifest={"format":"renshi-production-backup-v1","artifacts":{}}
        for name,source in files.items():
            encrypted=p.encrypt_file(source,self.bundle/name,settings.PRODUCTION_BACKUP_ENCRYPTION_KEY)
            manifest["artifacts"][name]={"bytes":encrypted.stat().st_size,"sha256":p.sha256_file(encrypted)}
        self.save(manifest);return manifest
    def save(self, manifest):
        (self.bundle/"manifest.json").write_text(json.dumps(manifest),encoding="utf-8")
    def test_original_root_directory_backup_roundtrips(self):
        h.safe_extract_archive(self.archive(),self.root/"extracted")
        self.assertEqual((self.root/"extracted/folder/a.txt").read_bytes(),b"payload")
    def test_duplicate_root_rejected(self):
        with self.assertRaises(h.SchoolHandoverError):
            h.inspect_archive(self.archive([(".",tarfile.DIRTYPE,b""),("./",tarfile.DIRTYPE,b"")]))
    def test_root_file_is_not_a_directory(self):
        with self.assertRaises(h.SchoolHandoverError):h.inspect_archive(self.archive([(".",tarfile.REGTYPE,b"bad")]))
    def test_root_counts_toward_resource_limit(self):
        with self.assertRaises(h.SchoolHandoverError):h.inspect_archive(self.archive(),max_members=1)
    def test_empty_live_media_refused_by_both_restore_routes(self):
        for cls in (dr.Command,school.Command):
            with self.subTest(cls=cls),self.assertRaises(h.SchoolHandoverError):cls._validate_media_target(self.media)
        self.assertFalse(list(self.media.iterdir()))
    def test_live_media_descendant_refused(self):
        for cls in (dr.Command,school.Command):
            with self.assertRaises(h.SchoolHandoverError):cls._validate_media_target(self.media/"restored")
    def test_live_media_parent_refused(self):
        with self.assertRaises(h.SchoolHandoverError):dr.Command._validate_media_target(self.root)
    def test_backup_storage_cannot_be_restore_media(self):
        with self.assertRaises(h.SchoolHandoverError):dr.Command._validate_media_target(self.root/"backups"/"restored")
    def test_static_or_frontend_cannot_be_restore_media(self):
        for path in (self.root/"static",self.root/"repo/frontend/new"):
            with self.assertRaises(h.SchoolHandoverError):dr.Command._validate_media_target(path)
    def test_symlink_target_rejected_before_resolving(self):
        target=self.root/"separate";target.mkdir();alias=self.root/"alias";alias.symlink_to(target,target_is_directory=True)
        with self.assertRaises(h.SchoolHandoverError):dr.Command._validate_media_target(alias)
    def test_symlink_parent_rejected(self):
        alias=self.root/"alias";alias.symlink_to(self.root,target_is_directory=True)
        with self.assertRaises(h.SchoolHandoverError):dr.Command._validate_media_target(alias/"not-yet-created")
    def test_independent_empty_target_accepted_without_creating(self):
        target=self.root/"restored";self.assertEqual(dr.Command._validate_media_target(target),target)
        self.assertFalse(target.exists())
    def test_no_media_target_is_supported(self):self.assertIsNone(dr.Command._validate_media_target(None))
    def test_existing_user_file_not_deleted(self):
        target=self.root/"restored";target.mkdir();(target/"keep").write_text("keep")
        with self.assertRaises(h.SchoolHandoverError):dr.Command._validate_media_target(target)
        self.assertEqual((target/"keep").read_text(),"keep")
    def test_valid_original_encrypted_bundle_verifies(self):
        self.make_bundle();out=io.StringIO();verify.Command(stdout=out).handle(bundle="bundle")
        self.assertIn("PRODUCTION_BACKUP_VERIFIED",out.getvalue())
    def test_unknown_artifact_name_rejected(self):
        m=self.make_bundle();m["artifacts"]["extra.enc"]=m["artifacts"]["database.sql.enc"];self.save(m)
        with self.assertRaises(p.ProductionBackupError):p.verified_bundle_manifest(self.bundle)
    def test_parent_traversal_inventory_rejected_before_decrypt(self):
        m=self.make_bundle();m["artifacts"]["../../outside.sql.enc"]=m["artifacts"].pop("database.sql.enc");self.save(m)
        with patch.object(verify,"decrypt_file") as decrypt:
            with self.assertRaises(CommandError):verify.Command().handle(bundle="bundle")
        decrypt.assert_not_called();self.assertFalse((self.root/"outside.sql").exists())
    def test_missing_media_rejected(self):
        m=self.make_bundle();m["artifacts"].pop("media.tar.gz.enc");self.save(m)
        with self.assertRaises(p.ProductionBackupError):p.verified_bundle_manifest(self.bundle)
    def test_boolean_size_rejected(self):
        m=self.make_bundle();m["artifacts"]["media.tar.gz.enc"]["bytes"]=True;self.save(m)
        with self.assertRaises(p.ProductionBackupError):p.verified_bundle_manifest(self.bundle)
    def test_mismatched_bytes_rejected(self):
        m=self.make_bundle();m["artifacts"]["media.tar.gz.enc"]["bytes"]+=1;self.save(m)
        with self.assertRaises(p.ProductionBackupError):p.verified_bundle_manifest(self.bundle)
    def test_bad_checksum_rejected(self):
        m=self.make_bundle();m["artifacts"]["database.sql.enc"]["sha256"]="0"*64;self.save(m)
        with self.assertRaises(p.ProductionBackupError):p.verified_bundle_manifest(self.bundle)
    def test_artifact_symlink_rejected(self):
        self.make_bundle();artifact=self.bundle/"database.sql.enc";moved=self.root/"moved";artifact.rename(moved);artifact.symlink_to(moved)
        with self.assertRaises(p.ProductionBackupError):p.verified_bundle_manifest(self.bundle)
    def test_manifest_symlink_rejected(self):
        self.make_bundle();moved=self.root/"manifest";path=self.bundle/"manifest.json";path.rename(moved);path.symlink_to(moved)
        with self.assertRaises(p.ProductionBackupError):p.verified_bundle_manifest(self.bundle)
    def test_manifest_duplicate_fields_rejected(self):
        self.make_bundle();path=self.bundle/"manifest.json";text=path.read_text();path.write_text(text.replace('{','{"format":"renshi-production-backup-v1",',1))
        with self.assertRaises(p.ProductionBackupError):p.verified_bundle_manifest(self.bundle)
    def test_authenticated_but_unsafe_media_is_not_verified(self):
        self.make_bundle([("escape",tarfile.SYMTYPE,b"")])
        with self.assertRaises(CommandError):verify.Command().handle(bundle="bundle")
    def restore_options(self):
        return dict(bundle="bundle",target_database="restored_db",confirm_target="restored_db",media_target=str(self.root/"restored"))
    def test_duplicate_inner_media_stops_before_sql_restore(self):
        self.make_bundle([("a",tarfile.REGTYPE,b"one"),("a",tarfile.REGTYPE,b"two")])
        with patch.dict(os.environ,{"RESTORE_DATABASE_USER":"test-user","RESTORE_DATABASE_PASSWORD":"test-only"}), \
             patch.object(dr,"resolve_mysql_client",return_value="mysql-test-only"), \
             patch.object(dr.Command,"_require_empty_database"),patch.object(dr.subprocess,"run") as run:
            with self.assertRaises(CommandError):dr.Command().handle(**self.restore_options())
        run.assert_not_called();self.assertFalse((self.root/"restored").exists())
    def test_valid_restore_stages_actual_media_before_mocked_sql(self):
        self.make_bundle()
        def check_sql(command,**kwargs):
            self.assertIn(b"CREATE TABLE",kwargs["stdin"].read())
            self.assertFalse((self.root/"restored").exists())
            return SimpleNamespace(returncode=0)
        with patch.dict(os.environ,{"RESTORE_DATABASE_USER":"test-user","RESTORE_DATABASE_PASSWORD":"test-only"}), \
             patch.object(dr,"resolve_mysql_client",return_value="mysql-test-only"), \
             patch.object(dr.Command,"_require_empty_database"),patch.object(dr.subprocess,"run",side_effect=check_sql) as run:
            dr.Command(stdout=io.StringIO()).handle(**self.restore_options())
        self.assertEqual(run.call_count,1);self.assertEqual((self.root/"restored/folder/a.txt").read_bytes(),b"payload")
    def test_late_file_in_target_is_not_deleted_after_mocked_sql(self):
        self.make_bundle()
        def concurrent_write(command,**kwargs):
            target=self.root/"restored";target.mkdir();(target/"keep").write_text("keep")
            return SimpleNamespace(returncode=0)
        with patch.dict(os.environ,{"RESTORE_DATABASE_USER":"test-user","RESTORE_DATABASE_PASSWORD":"test-only"}), \
             patch.object(dr,"resolve_mysql_client",return_value="mysql-test-only"), \
             patch.object(dr.Command,"_require_empty_database"),patch.object(dr.subprocess,"run",side_effect=concurrent_write):
            with self.assertRaises(CommandError):dr.Command().handle(**self.restore_options())
        self.assertEqual((self.root/"restored/keep").read_text(),"keep")

    def test_source_code_directory_is_not_restore_destination(self):
        for cls in (dr.Command,school.Command):
            with self.assertRaises(h.SchoolHandoverError):cls._validate_media_target(self.root/"repo/backend/new")
    def test_live_database_case_alias_rejected_before_any_sql(self):
        with patch.object(dr.subprocess,"run") as run:
            with self.assertRaisesRegex(CommandError,"live configured"):
                dr.Command().handle(bundle="unused",target_database="LIVE_DB",confirm_target="LIVE_DB",media_target=None)
            with self.assertRaisesRegex(CommandError,"live configured"):
                school.Command().handle(package="unused",target_database="LIVE_DB",confirm_target="LIVE_DB",media_target=None,
                    operator="test",confirm_restore_policy=h.HANDOVER_RESTORE_CONFIRMATION)
        run.assert_not_called()
    def test_aliased_table_inventory_rejected(self):
        (self.root/"table_row_counts.json").write_text(json.dumps([
            {"table_name":"staff", "row_count":1},{"table_name":"STAFF", "row_count":1}]))
        with patch.object(school.Command,"_query_scalar",return_value="1"):
            with self.assertRaisesRegex(ValueError,"duplicate"):
                school.Command._post_restore_check(client="unused",target="unused",host="unused",port="0",user="unused",environment={},
                    manifest={"stats":{},"_extracted_root":str(self.root)})
    def test_negative_table_inventory_count_rejected(self):
        (self.root/"table_row_counts.json").write_text(json.dumps([{"table_name":"staff", "row_count":-1}]))
        with patch.object(school.Command,"_query_scalar",return_value="1"):
            with self.assertRaisesRegex(ValueError,"invalid count"):
                school.Command._post_restore_check(client="unused",target="unused",host="unused",port="0",user="unused",environment={},
                    manifest={"stats":{},"_extracted_root":str(self.root)})
