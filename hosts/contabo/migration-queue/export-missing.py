#!/usr/bin/env python3
"""Plan read-only SHA256 path recovery and export exact missing Takeout entries.

No metadata sidecars are fabricated. Optional JSON files are not presumed
to exist when absent from the original manifest.
"""
import argparse
import collections
import hashlib
import json
from pathlib import Path

def digest(path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(4*1024*1024),b""):
            h.update(chunk)
    return h.hexdigest()

def audit(root, manifest):
    locations=collections.defaultdict(list)
    for p in sorted(root.rglob("*")):
        if p.is_symlink():
            raise RuntimeError("Symlink refused: "+str(p))
        if not p.is_file():
            continue
        before=p.stat()
        key=(before.st_size,digest(p))
        after=p.stat()
        if (before.st_size,before.st_mtime_ns,before.st_ctime_ns)!=(after.st_size,after.st_mtime_ns,after.st_ctime_ns):
            raise RuntimeError("Upload changed during audit: "+str(p))
        locations[key].append(p.relative_to(root).as_posix())
    present=[]; recoverable={}; missing=[]
    for rel, meta in sorted(manifest.items()):
        key=(meta["size"],meta["sha256"])
        candidates=locations.get(key,[])
        if rel in candidates:
            present.append(rel)
        elif candidates:
            recoverable[rel]=candidates
        else:
            missing.append(rel)
    return present,recoverable,missing,locations

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--root",default="/var/lib/nextcloud/data/wug/files/Photos/Google Photos")
    p.add_argument("--manifest",default="/var/lib/migration-queue/photos-manifest.json")
    p.add_argument("--output",default="/var/lib/migration-queue/photos-missing.txt")
    p.add_argument("--plan",default="/var/lib/migration-queue/photos-recovery-plan.json")
    args=p.parse_args()
    manifest=json.loads(Path(args.manifest).read_text())["files"]
    exact,recoverable,missing,locations=audit(Path(args.root),manifest)
    suffix=".supplemental-metadata.json"
    categories={
      "supplemental_metadata_json":sum(x.endswith(suffix) for x in missing),
      "other_json":sum(x.endswith(".json") and not x.endswith(suffix) for x in missing),
      "non_json":sum(not x.endswith(".json") for x in missing)
    }
    report={"exact":len(exact),"recoverable":len(recoverable),"missing":len(missing),
            "categories":categories,"missing_paths":missing,
            "recoverable_paths":recoverable}
    Path(args.output).parent.mkdir(parents=True,exist_ok=True)
    Path(args.output).write_text("\n".join(missing)+("\n" if missing else ""))
    Path(args.plan).write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n")
    print(json.dumps({"exact":len(exact),"recoverable":len(recoverable),"missing":len(missing),
        "categories":categories,"missing_list":args.output,"recovery_plan":args.plan,
        "first_20_missing":missing[:20]},indent=2))

if __name__=="__main__":
    main()
