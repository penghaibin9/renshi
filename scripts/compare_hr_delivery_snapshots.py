"""Compare source/restored proofs; no database writes or release approval.

Exit 0 means valid supplied MySQL8.4 artifacts from different named databases
match. It is not collector authentication or a real restore execution record.
"""
import argparse
import json
from pathlib import Path
import re
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"backend"))
from hr_onboarding.services.delivery_snapshot import compare_snapshots


def _unique_pairs(pairs):
    result = {}
    for key,value in pairs:
        if key in result:
            raise ValueError("Duplicate proof key")
        result[key]=value
    return result


def _reject_constant(value):
    raise ValueError("Non-finite JSON value")


def read_proof(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 8*1024*1024:
        raise ValueError("Proof must be a regular JSON file of at most 8 MiB")
    with path.open("rb") as stream:
        data=stream.read(8*1024*1024+1)
    if len(data)>8*1024*1024:
        raise ValueError("Proof grew beyond the resource limit")
    value=json.loads(data.decode("utf-8"),object_pairs_hook=_unique_pairs,parse_constant=_reject_constant)
    if not isinstance(value,dict):
        raise ValueError("Proof root must be an object")
    return value


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source",type=Path);parser.add_argument("restored",type=Path)
    args=parser.parse_args(argv)
    try:
        if args.source.samefile(args.restored):
            raise ValueError("Source and restored proofs are the same file")
        left=read_proof(args.source); right=read_proof(args.restored)
        result=compare_snapshots(left,right)
        content_status=result["status"]
        result["mysql_evidence"]=all(p.get("database_vendor")=="mysql"
            and isinstance(p.get("database_version"),str)
            and bool(re.fullmatch(r"8\.4\.[0-9]+(?:[-+].*)?",p["database_version"]))
            and "mariadb" not in p["database_version"].lower()
            and p.get("writes_performed") is False and p.get("release_approved") is False
            for p in (left,right))
        names=[p.get("database_name") for p in (left,right)]
        result["independent_database"]=(all(isinstance(n,str) and n.strip()==n and bool(n) for n in names)
            and names[0].casefold()!=names[1].casefold())
        result["content_status"]=content_status
        if not result["mysql_evidence"] or not result["independent_database"]:
            result["status"]="BLOCKED"
            result["issues"].append("REAL_MYSQL_OR_INDEPENDENT_DATABASE_EVIDENCE_MISSING")
    except (OSError,ValueError,TypeError,RecursionError) as exc:
        result={"status":"BLOCKED","release_approved":False,
            "reason":type(exc).__name__+": invalid, reused or unreadable proof file"}
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0 if result["status"]=="MATCH" else 2

if __name__=="__main__":
    raise SystemExit(main())
