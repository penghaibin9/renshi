import copy, importlib.util, json, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location("v13_proof",ROOT/"backend/hr_onboarding/services/delivery_snapshot.py")
p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)

class EvidenceCloseoutTests(unittest.TestCase):
    def proof(self):
        return {"schema":p.SCHEMA,"school_id":"111","key_id":p.key_id(b"a"*32),
            "captured_at":"2026-09-19T00:00:00+00:00",
            "scope":"FIRST_CUSTOMER_PERSONNEL_AND_ONBOARDING_ROWS_ONLY",
            "models":{name:{"rows":1,"shape_sha256":"a"*64,"content_hmac_sha256":"b"*64} for name in p.MODEL_LABELS}}
    def rejected(self,mutate):
        a=self.proof();mutate(a)
        self.assertNotEqual(p.compare_snapshots(a,copy.deepcopy(a))["status"],"MATCH")
    def test_missing_school_on_both_is_rejected(self):self.rejected(lambda a:a.pop("school_id"))
    def test_negative_school_on_both_is_rejected(self):self.rejected(lambda a:a.update(school_id="-1"))
    def test_nonnumeric_school_on_both_is_rejected(self):self.rejected(lambda a:a.update(school_id="unknown"))
    def test_arbitrary_key_id_on_both_is_rejected(self):self.rejected(lambda a:a.update(key_id="x"))
    def test_nondigest_hmac_on_both_is_rejected(self):self.rejected(lambda a:a["models"][p.MODEL_LABELS[0]].update(content_hmac_sha256="z"*64))
    def test_missing_scope_on_both_is_rejected(self):self.rejected(lambda a:a.pop("scope"))
    def test_different_scope_on_both_is_rejected(self):self.rejected(lambda a:a.update(scope="OTHER_TABLES"))
    def test_invalid_time_on_both_is_rejected(self):self.rejected(lambda a:a.update(captured_at="sometime"))
    def test_naive_time_on_both_is_rejected(self):self.rejected(lambda a:a.update(captured_at="2026-09-19T00:00:00"))
    def test_non_objects_report_mismatch_not_exception(self):
        self.assertNotEqual(p.compare_snapshots([],None)["status"],"MATCH")
    def test_well_formed_records_match_without_release_approval(self):
        result=p.compare_snapshots(self.proof(),self.proof())
        self.assertEqual(result["status"],"MATCH");self.assertIs(result["release_approved"],False)
