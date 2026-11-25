"""Compose the pinned Red duel build with the mode and navigation extension."""
import argparse
from difflib import unified_diff
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from build_arena_pace import check, read, sha

NATIVE=Path(__file__).resolve().parent


def build(args):
    out=args.output.resolve()
    check(not out.exists() and not any((p/".git").exists() for p in [out,*out.parents]),"Fresh external output required")
    base=NATIVE/"red-policy-build.json"
    check(sha(base)=="2ab4ec3862fabc55d328a2de2ec464b1d19f6cf3e5002d1f26bf994bad89d5e2","Wrong frozen duel build")
    pins=read(base)
    for filename,field in (("red-policy.patch","policy_patch_sha256"),("red_policy.inc","policy_source_sha256"),
                           ("build_red_policy.py","builder_sha256")):
        check(sha(NATIVE/filename)==pins[field],"Duel file changed: "+filename)
    with tempfile.TemporaryDirectory(prefix="adjoin-transfer-") as tmp:
        stage=Path(tmp)/"source/native"; stage.mkdir(parents=True)
        for filename in ("build_red_policy.py","build_arena_pace.py","build_planner_go.py","red_policy.inc",
                         "pace-build.json","planner-go-build.json","arena_pace.c"):
            shutil.copyfile(NATIVE/filename,stage/filename)
        combined=(NATIVE/"red-policy.patch").read_text()+(NATIVE/"red-transfer.patch").read_text()
        for name in ("red_transfer.inc","red_nav_recall.h"):
            combined+="".join(unified_diff([], (NATIVE/name).read_text().splitlines(True), "/dev/null","b/src/AI/"+name))
        (stage/"red-policy.patch").write_text(combined)
        cmd=[sys.executable,"-B",str(stage/"build_red_policy.py"),"--red-export",str(args.red_export.resolve()),
             "--globals-header",str(args.globals_header.resolve()),"--output",str(Path(tmp)/"built")]
        for src in args.source: cmd+=["--source",str(src.resolve())]
        subprocess.run(cmd,check=True)
        result=read(Path(tmp)/"built/red-policy-build.json")
        result.update(duel_receipt_sha256=sha(base),duel_binary_sha256=pins["binary_sha256"],
            policy_patch_sha256=pins["policy_patch_sha256"],composed_patch_sha256=sha(stage/"red-policy.patch"),
            transfer_patch_sha256=sha(NATIVE/"red-transfer.patch"),transfer_source_sha256=sha(NATIVE/"red_transfer.inc"),
            nav_recall_sha256=sha(NATIVE/"red_nav_recall.h"),transfer_builder_sha256=sha(Path(__file__)))
        receipt=(json.dumps(result,indent=2)+"\n").encode()
        retained=NATIVE/"red-transfer-build.json"
        if retained.exists(): check(receipt==retained.read_bytes(),"Transfer rebuild differs from retained receipt")
        out.mkdir(parents=True)
        for name in ("jk-bot-client","libGameNetworkingSockets.so"): shutil.copy2(Path(tmp)/"built"/name,out/name)
        (out/"red-transfer-build.json").write_bytes(receipt)
        print(result["binary_sha256"],out)


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--red-export",required=True,type=Path)
    p.add_argument("--source",required=True,action="append",type=Path)
    p.add_argument("--globals-header",required=True,type=Path)
    p.add_argument("--output",required=True,type=Path)
    build(p.parse_args())
