"""Rebuild the route-hint client from the frozen supported-platform client."""
import argparse
import difflib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from build_red_platform import BUILD_INPUTS, digest

NATIVE=Path(__file__).resolve().parent
PLATFORM_RECEIPT="d0e9c69aa32543fec11b19f89caf557ea7dbb6e0bc9e6c991023d81a0618e45f"


def build(args):
    receipt=NATIVE/"red-platform-build.json"
    if digest(receipt)!=PLATFORM_RECEIPT:raise ValueError("Unexpected platform parent")
    parent=json.loads(receipt.read_bytes())
    for name,key in (("red-platform.patch","platform_patch_sha256"),("red_platform.inc","platform_source_sha256"),
                     ("build_red_platform.py","platform_builder_sha256")):
        if digest(NATIVE/name)!=parent[key]:raise ValueError("Unexpected platform input "+name)
    out=args.output.resolve()
    if out.exists() or any((part/".git").exists() for part in (out,*out.parents)):raise ValueError("Use fresh external output")
    with tempfile.TemporaryDirectory(prefix="adjoin-route-hint-") as temp:
        work=Path(temp)
        for name in (*BUILD_INPUTS,"red-custom-build.json","red-custom.patch","build_red_platform.py","red_platform.inc"):
            shutil.copyfile(NATIVE/name,work/name)
        source=NATIVE/"red_hint.inc";patch=NATIVE/"red-hint.patch"
        append="".join(difflib.unified_diff([],source.read_text().splitlines(True),"/dev/null","b/src/AI/red_hint.inc"))
        (work/"red-platform.patch").write_bytes((NATIVE/"red-platform.patch").read_bytes()+patch.read_bytes()+append.encode())
        built=work/"images"
        cmd=[sys.executable,"-B",work/"build_red_platform.py","--red-export",args.red_export,
             "--globals-header",args.globals_header,"--output",built]
        for root in args.source:cmd.extend(("--source",root))
        subprocess.run(cmd,check=True)
        current=json.loads((built/"red-platform-build.json").read_bytes())
        for unit,sha in parent["rebuilt_objects"].items():
            if unit!="AI/jkBot" and current["rebuilt_objects"][unit]!=sha:raise ValueError("Unexpected changed object "+unit)
        result=dict(current,platform_patch_sha256=parent["platform_patch_sha256"],platform_receipt_sha256=PLATFORM_RECEIPT,
                    platform_binary_sha256=parent["binary_sha256"],hint_patch_sha256=digest(patch),
                    hint_source_sha256=digest(source),hint_builder_sha256=digest(Path(__file__)))
        raw=(json.dumps(result,indent=2)+"\n").encode();pin=NATIVE/"red-hint-build.json"
        if pin.exists() and raw!=pin.read_bytes():raise ValueError("Unexpected hint image or receipt")
        out.mkdir(parents=True)
        for name in ("jk-bot-client","libGameNetworkingSockets.so"):shutil.copy2(built/name,out/name)
        (out/"red-hint-build.json").write_bytes(raw)
        print(result["binary_sha256"],out)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--red-export",required=True,type=Path)
    parser.add_argument("--globals-header",required=True,type=Path)
    parser.add_argument("--source",required=True,action="append",type=Path)
    parser.add_argument("--output",required=True,type=Path)
    build(parser.parse_args())
