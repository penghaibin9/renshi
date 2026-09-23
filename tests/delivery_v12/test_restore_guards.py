import importlib.util,io,json,os,tarfile,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
def load(name,rel):
    spec=importlib.util.spec_from_file_location(name,ROOT/rel);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
h=load("v12_handover","backend/horilla_backup/handover.py")
p=load("v12_proof","backend/hr_onboarding/services/delivery_snapshot.py")

class ArchiveGuardTests(unittest.TestCase):
    def archive(self,root,entries):
        path=root/"test.tar.gz"
        with tarfile.open(path,"w:gz") as z:
            for name,kind,body in entries:
                i=tarfile.TarInfo(name);i.type=kind;i.size=len(body) if kind==tarfile.REGTYPE else 0
                if kind==tarfile.SYMTYPE:i.linkname="outside"
                z.addfile(i,io.BytesIO(body) if kind==tarfile.REGTYPE else None)
        return path
    def rejects(self,entries,**limits):
        with tempfile.TemporaryDirectory() as t:
            with self.assertRaises(h.SchoolHandoverError):h.inspect_archive(self.archive(Path(t),entries),**limits)
    def test_duplicate_path(self):self.rejects([("a",tarfile.REGTYPE,b"1"),("a",tarfile.REGTYPE,b"2")])
    def test_dot_alias(self):self.rejects([("a",tarfile.REGTYPE,b"1"),("./a",tarfile.REGTYPE,b"2")])
    def test_case_alias(self):self.rejects([("File",tarfile.REGTYPE,b"1"),("file",tarfile.REGTYPE,b"2")])
    def test_file_directory_collision(self):self.rejects([("a/b",tarfile.REGTYPE,b"1"),("a",tarfile.REGTYPE,b"2")])
    def test_windows_drive(self):self.rejects([("C:/escape",tarfile.REGTYPE,b"1")])
    def test_windows_ads(self):self.rejects([("a:secret",tarfile.REGTYPE,b"1")])
    def test_windows_device(self):self.rejects([("NUL.txt",tarfile.REGTYPE,b"1")])
    def test_parent_path(self):self.rejects([("../escape",tarfile.REGTYPE,b"1")])
    def test_symlink(self):self.rejects([("link",tarfile.SYMTYPE,b"")])
    def test_member_limit(self):self.rejects([("a",tarfile.REGTYPE,b"12")],max_member_bytes=1)
    def test_expanded_limit(self):self.rejects([("a",tarfile.REGTYPE,b"12"),("b",tarfile.REGTYPE,b"34")],max_expanded_bytes=3)
    def test_count_limit(self):self.rejects([("a",tarfile.REGTYPE,b"1"),("b",tarfile.REGTYPE,b"2")],max_members=1)
    def test_extract_refuses_nonempty_destination(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);dest=root/"out";dest.mkdir();(dest/"keep").write_text("keep")
            arc=self.archive(root,[("keep",tarfile.REGTYPE,b"overwrite")])
            with self.assertRaises(h.SchoolHandoverError):h.safe_extract_archive(arc,dest)
            self.assertEqual((dest/"keep").read_text(),"keep")
    def test_reject_all_before_writing_a_good_first_file(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);arc=self.archive(root,[("good",tarfile.REGTYPE,b"1"),("../bad",tarfile.REGTYPE,b"2")])
            with self.assertRaises(h.SchoolHandoverError):h.safe_extract_archive(arc,root/"out")
            self.assertFalse((root/"out/good").exists())
    def test_valid_private_roundtrip(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);arc=self.archive(root,[("dir",tarfile.DIRTYPE,b""),("dir/file",tarfile.REGTYPE,b"data")])
            h.safe_extract_archive(arc,root/"out")
            self.assertEqual((root/"out/dir/file").read_bytes(),b"data")
            self.assertEqual((root/"out/dir/file").stat().st_mode & 0o777,0o600)
    def test_non_object_manifest_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            (Path(t)/"manifest.json").write_text("[]")
            with self.assertRaises(h.SchoolHandoverError):h.load_and_verify_manifest(Path(t))

class SnapshotProofTests(unittest.TestCase):
    def record(self,rows=()):
        return {"schema":p.SCHEMA,"school_id":"111","key_id":p.key_id(b"a"*32),
            "scope":p.SCOPE,"captured_at":"2026-09-19T00:00:00+00:00","models":{
            label:{**p.fingerprint_rows(rows,b"a"*32,domain=label),"shape_sha256":"a"*64} for label in p.MODEL_LABELS}}
    def test_same_rows_match(self):self.assertEqual(p.compare_snapshots(self.record([{"id":1}]),self.record([{"id":1}]))["status"],"MATCH")
    def test_equal_counts_changed_content_fails(self):self.assertEqual(p.compare_snapshots(self.record([{"id":1,"v":5}]),self.record([{"id":1,"v":6}]))["status"],"MISMATCH")
    def test_wrong_key_fails(self):
        a=self.record();b=self.record();b["key_id"]=p.key_id(b"b"*32)
        self.assertIn("KEY_MISMATCH",p.compare_snapshots(a,b)["issues"])
    def test_wrong_school_fails(self):
        a=self.record();b=self.record();b["school_id"]="222"
        self.assertIn("SCHOOL_MISMATCH",p.compare_snapshots(a,b)["issues"])
    def test_missing_model_fails(self):
        a=self.record();b=self.record();b["models"].pop(next(iter(b["models"])))
        self.assertIn("MODEL_SCOPE_MISMATCH",p.compare_snapshots(a,b)["issues"])
    def test_output_contains_no_original_values(self):
        proof=self.record([{"name":"private-name","bank":"1234567"}])
        self.assertNotIn("private-name",json.dumps(proof));self.assertNotIn("1234567",json.dumps(proof))
    def test_short_key_rejected(self):
        with self.assertRaises(ValueError):p.key_id(b"short")
    def test_hash_match_never_approves_release(self):self.assertFalse(p.compare_snapshots(self.record(),self.record())["release_approved"])
