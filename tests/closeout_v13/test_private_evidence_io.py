import contextlib,copy,importlib.util,io,json,os,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import patch
from hr_onboarding.services.delivery_evidence_io import read_private_key,write_new_private_json
from hr_onboarding.services import delivery_snapshot as p
ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location("v13_compare_cli",ROOT/"scripts/compare_hr_delivery_snapshots.py")
cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)

class PrivateEvidenceIOTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
    def test_private_key_read(self):
        key=self.root/"key";key.write_bytes(b"k"*32);key.chmod(0o600)
        self.assertEqual(read_private_key(key),b"k"*32)
    def test_oversized_key_rejected(self):
        key=self.root/"key";key.write_bytes(b"k"*4097);key.chmod(0o600)
        with self.assertRaises(ValueError):read_private_key(key)
    def test_short_key_rejected(self):
        key=self.root/"key";key.write_bytes(b"k"*31);key.chmod(0o600)
        with self.assertRaises(ValueError):read_private_key(key)
    def test_public_key_permissions_rejected(self):
        key=self.root/"key";key.write_bytes(b"k"*32);key.chmod(0o644)
        with self.assertRaises(ValueError):read_private_key(key)
    def test_key_link_rejected(self):
        key=self.root/"key";key.write_bytes(b"k"*32);key.chmod(0o600);alias=self.root/"link";alias.symlink_to(key)
        with self.assertRaises(ValueError):read_private_key(alias)
    def test_fifo_key_rejected_without_waiting(self):
        key=self.root/"pipe";os.mkfifo(key,0o600)
        with self.assertRaises(ValueError):read_private_key(key)
    def test_complete_private_output(self):
        path=self.root/"proof.json";write_new_private_json(path,{"ok":True})
        self.assertTrue(json.loads(path.read_text())["ok"]);self.assertEqual(path.stat().st_mode&0o777,0o600)
        self.assertFalse(list(self.root.glob("*.tmp")))
    def test_old_evidence_never_overwritten(self):
        path=self.root/"proof.json";path.write_text("old")
        with self.assertRaises(ValueError):write_new_private_json(path,{"ok":True})
        self.assertEqual(path.read_text(),"old")
    def test_configuration_path_rejected(self):
        with self.assertRaises(ValueError):write_new_private_json(self.root/".env",{"ok":True})
        self.assertFalse((self.root/".env").exists())
    def test_failed_serialization_exposes_no_partial_evidence(self):
        path=self.root/"proof.json"
        with self.assertRaises(ValueError):write_new_private_json(path,{"bad":float("nan")})
        self.assertFalse(path.exists());self.assertFalse(list(self.root.glob("*.tmp")))
    def test_link_parent_rejected(self):
        alias=self.root/"alias";alias.symlink_to(self.root,target_is_directory=True)
        with self.assertRaises(ValueError):write_new_private_json(alias/"proof.json",{})
    def test_concurrent_publish_exactly_one_winner(self):
        path=self.root/"proof.json";barrier=threading.Barrier(2);out=[]
        def publish(n):
            barrier.wait()
            try:write_new_private_json(path,{"n":n});out.append("ok")
            except (FileExistsError,ValueError):out.append("rejected")
        threads=[threading.Thread(target=publish,args=(n,)) for n in (1,2)]
        for t in threads:t.start()
        for t in threads:t.join(3)
        self.assertCountEqual(out,["ok","rejected"]);self.assertIn(json.loads(path.read_text())["n"],(1,2))
    def proof(self,db):
        return {"schema":p.SCHEMA,"scope":p.SCOPE,"school_id":"111","key_id":p.key_id(b"k"*32),
            "captured_at":"2026-09-19T00:00:00+00:00","database_vendor":"mysql","database_version":"8.4.6",
            "database_name":db,"writes_performed":False,"release_approved":False,
            "models":{label:{"rows":1,"shape_sha256":"a"*64,"content_hmac_sha256":"b"*64} for label in p.MODEL_LABELS}}
    def compare(self,left,right):
        a=self.root/"a.json";b=self.root/"b.json";a.write_text(json.dumps(left));b.write_text(json.dumps(right))
        out=io.StringIO()
        with contextlib.redirect_stdout(out):code=cli.main([str(a),str(b)])
        return code,json.loads(out.getvalue())
    def test_good_declared_mysql_proofs_match_without_acceptance(self):
        code,result=self.compare(self.proof("source"),self.proof("restored"))
        self.assertEqual(code,0);self.assertEqual(result["status"],"MATCH");self.assertIs(result["release_approved"],False)
    def test_missing_mysql_never_prints_overall_match(self):
        a=self.proof("a");b=self.proof("b");a["database_vendor"]="sqlite"
        code,result=self.compare(a,b);self.assertEqual(code,2);self.assertEqual(result["status"],"BLOCKED")
        self.assertEqual(result["content_status"],"MATCH")
    def test_same_database_never_prints_match(self):
        code,result=self.compare(self.proof("source"),self.proof("source"))
        self.assertEqual(code,2);self.assertEqual(result["status"],"BLOCKED")
    def test_reused_file_is_rejected(self):
        path=self.root/"a.json";path.write_text(json.dumps(self.proof("a")));out=io.StringIO()
        with contextlib.redirect_stdout(out):code=cli.main([str(path),str(path)])
        self.assertEqual(code,2);self.assertEqual(json.loads(out.getvalue())["status"],"BLOCKED")
    def test_duplicate_json_keys_rejected(self):
        path=self.root/"a.json";path.write_text('{"school_id":"1","school_id":"2"}')
        with self.assertRaises(ValueError):cli.read_proof(path)
    def test_nan_json_rejected(self):
        path=self.root/"a.json";path.write_text('{"bad":NaN}')
        with self.assertRaises(ValueError):cli.read_proof(path)
    def test_fake_mysql_version_rejected(self):
        a=self.proof("a");a["database_version"]="8.4.fake"
        code,result=self.compare(a,self.proof("b"));self.assertEqual(code,2)
    def test_old_proof_version_cannot_silently_match(self):
        a=self.proof("a");b=self.proof("b");a["schema"]=b["schema"]="yueke.delivery-content-proof.1"
        code,result=self.compare(a,b);self.assertEqual(code,2)


class KeyPathCloseoutTests(unittest.TestCase):
    def test_symbolic_key_parent_is_rejected(self):
        from hr_onboarding.services.delivery_evidence_io import read_private_key
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);real=root/"private";real.mkdir()
            key=real/"key";key.write_bytes(b"x"*32);key.chmod(0o600)
            alias=root/"alias";alias.symlink_to(real,target_is_directory=True)
            with self.assertRaises(ValueError):read_private_key(alias/"key")
