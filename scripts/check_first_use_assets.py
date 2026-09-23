"""Validate/reuse the user's own baseline deployment assets; never download fonts."""
import argparse,hashlib,json,sys,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser(description='核对原工程部署资产；仅从用户自己的同基线包补齐，不访问网络。')
    parser.add_argument('--baseline-zip',type=Path)
    args=parser.parse_args()
    manifest=json.loads((ROOT/'FIRST_USE_EXTERNAL_ASSETS.json').read_text())
    source=None
    if args.baseline_zip:
        if hashlib.sha256(args.baseline_zip.read_bytes()).hexdigest()!=manifest['baseline_sha256']:
            raise SystemExit('原始基线SHA256不符，拒绝补齐。')
        source=zipfile.ZipFile(args.baseline_zip)
    missing=[]
    try:
        for item in manifest['files']:
            path=(ROOT/item['path']).resolve()
            if ROOT not in path.parents:raise SystemExit('资产路径非法')
            if path.exists():
                if hashlib.sha256(path.read_bytes()).hexdigest()!=item['sha256']:
                    raise SystemExit('现有资产与基线不同，未覆盖：'+item['path'])
                continue
            if source is None:
                missing.append(item['path']);continue
            raw=source.read(item['path'])
            if hashlib.sha256(raw).hexdigest()!=item['sha256']:raise SystemExit('资产内容校验失败')
            path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
    finally:
        if source:source.close()
    if missing:
        print('缺少原工程部署资产：'+str(len(missing))+' 项。保留原工作区资产，或用 --baseline-zip 指定用户自己的同基线ZIP。')
        return 2
    print('原工程部署资产校验通过；未下载任何外部文件。');return 0

if __name__=='__main__':sys.exit(main())
