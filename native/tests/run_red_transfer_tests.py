"""Run Red's upstream driver and a persistent directed-edge route regression."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

NATIVE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(NATIVE))
from build_planner_go import read_pinned_sources, sha


def run(args):
    release=args.red_export.resolve()
    manifest=json.loads((release/"native/BOT_BUILD.json").read_text())
    assert sha(release/"native/bot-tactics.patch")=="0e409e379d0e6f088d9ddf469aaac54dc301e0111ce0ce08c5823d210f1857aa"
    with tempfile.TemporaryDirectory(prefix="adjoin-transfer-fixtures-") as tmp:
        work=Path(tmp); src=work/"source"; inc=work/"generated"; inc.mkdir()
        read_pinned_sources(release,[p.resolve() for p in args.source],src,manifest)
        for p in (release/"native/bot-tactics.patch",NATIVE/"red-policy.patch",NATIVE/"red-transfer.patch"):
            subprocess.run(["patch","--quiet","--batch","--fuzz=0","-p1","-i",p],cwd=src,check=True)
        for name in ("red_policy.inc","red_transfer.inc","red_nav_recall.h"):
            shutil.copyfile(NATIVE/name,src/"src/AI"/name)
        shutil.copyfile(args.globals_header,inc/"globals.h")
        flags=json.loads((NATIVE/"planner-go-build.json").read_text())["compile_flags"]
        flags=[f for f in flags if f not in ("-O3","-DNDEBUG","-D_FORTIFY_SOURCE=3")]
        cmd=["cc",*flags,"-O1","-ffunction-sections","-fdata-sections","-I"+str(src/"src"),"-I"+str(inc),
             "-I"+str(release/"native/tests")]
        item=work/"item.o"
        subprocess.run([*cmd,"-c",src/"src/World/sithItem.c","-o",item],check=True)
        for preset,extra in (("legacy",[]),("default",["-DJKBOT_TEST_NEW_DEFAULTS"])):
            cache=work/preset; cache.mkdir()
            exe=work/("check-"+preset)
            # Recovered engine headers declare unused static legacy address pointers.
            subprocess.run([*cmd,*extra,"-Wall","-Wextra","-Werror","-Wno-unused-variable",NATIVE/"tests/test_red_transfer_driver.c",
                            item,"-Wl,--gc-sections","-lm","-lcrypto","-o",exe],check=True)
            subprocess.run([exe,cache],check=True)


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--red-export",required=True,type=Path)
    p.add_argument("--source",required=True,action="append",type=Path)
    p.add_argument("--globals-header",required=True,type=Path)
    run(p.parse_args())
