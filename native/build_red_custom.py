"""Rebuild the opt-in, hash-pinned local episode client on the measured transfer client."""
import argparse
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import tarfile
import tempfile

from build_arena_pace import HOOKS, check, link_file, read, read_pinned_sources, run, sha
from build_red_policy import RED_ARCHIVE, RED_BASE, RED_OVERLAY

NATIVE=Path(__file__).resolve().parent
TRANSFER_SHA="6be9ca776c133f494c5ca98a29dcec497babc5acdf723711a8a55b14fe900509"


def build(args):
    out=args.output.resolve()
    release=args.red_export.resolve()
    check(not out.exists() and all(not (p/".git").exists() for p in (out,*out.parents)), "Use fresh external output")
    original=NATIVE/"red-transfer-build.json"
    check(sha(original)==TRANSFER_SHA,"Wrong transfer parent")
    parent=read(original)
    for file,key in (("red-policy.patch","policy_patch_sha256"),("red_policy.inc","policy_source_sha256"),
                     ("red-transfer.patch","transfer_patch_sha256"),("red_transfer.inc","transfer_source_sha256"),
                     ("red_nav_recall.h","nav_recall_sha256"),("arena_pace.c","pace_source_sha256")):
        check(sha(NATIVE/file)==parent[key],"Wrong parent source "+file)
    overlay=release/"native/bot-tactics.patch"; archive=release/"native/bot-relink-linux-x86_64.tar.gz"
    check(sha(overlay)==RED_OVERLAY and sha(release/"native/bot-client.patch")==RED_BASE and sha(archive)==RED_ARCHIVE,
          "Wrong Red upstream inputs")
    check(sha(args.globals_header)==parent["generated_globals_sha256"],"Wrong generated globals")
    manifest=read(release/"native/BOT_BUILD.json")
    check(sha(release/"bin/bots-linux-x86_64/jk-bot-client")==parent["base_binary_sha256"],"Wrong upstream client")
    with tempfile.TemporaryDirectory(prefix="adjoin-custom-") as tmp:
        work=Path(tmp); src=work/"src"; objdir=work/"objects"; inc=work/"generated"; inc.mkdir()
        read_pinned_sources(release,[p.resolve() for p in args.source],src,manifest)
        for patch in (overlay,NATIVE/"red-policy.patch",NATIVE/"red-transfer.patch",NATIVE/"red-custom.patch"):
            run(["patch","--quiet","--batch","--fuzz=0","-p1","-i",patch],cwd=src)
        for name in ("red_policy.inc","red_transfer.inc","red_nav_recall.h","red_custom.h"):
            shutil.copyfile(NATIVE/name,src/"src/AI"/name)
        shutil.copyfile(args.globals_header,inc/"globals.h")
        with tarfile.open(archive) as tar: tar.extractall(objdir,filter="data")
        for name,expected in manifest["relink_inputs"].items():
            check(sha(objdir/name)==expected,"Invalid link input "+name)
        engine=objdir/"CMakeFiles/sith_engine.dir/src"; rebuilt={};deps={}
        for unit in ("AI/jkBot","Devices/sithControl","Gui/jkGUIMultiplayer"):
            source=src/"src"/(unit+".c"); obj=engine/(unit+".c.o"); dep=work/"deps.d"
            # Keep the frozen stock Control diagnostic literal byte-identical.
            mapped="/tmp/adjoin-red-fj8jyjnc/source/src/Devices/sithControl.c" if unit=="Devices/sithControl" else "/src/"+unit+".c"
            run(["cc",*parent["flags"],f"-fmacro-prefix-map={source}={mapped}","-I"+str(src/"src"),"-I"+str(inc),
                 "-MMD","-MF",dep,"-c",source,"-o",obj])
            rebuilt[unit]=sha(obj)
            for name in shlex.split(dep.read_text().replace("\\\n"," ").split(":",1)[1]):
                path=Path(name)
                if path.is_relative_to(src): deps[path.relative_to(src).as_posix()]=sha(path)
        check(rebuilt["Devices/sithControl"]==parent["rebuilt_objects"]["Devices/sithControl"],"Stock control object changed")
        for unit,hooks in HOOKS.items():
            obj=engine/(unit+".c.o")
            refs={s.split()[-1] for s in subprocess.check_output(["nm","-u",obj],text=True).splitlines()}
            check(set(hooks)<=refs,"Missing clock hook")
            run(["objcopy",*[v for old,new in hooks.items() for v in ("--redefine-sym",old+"="+new)],obj])
        run(["cc","-std=c11","-O2","-Wall","-Wextra","-Werror","-fPIC","-c",NATIVE/"arena_pace.c","-o",objdir/"arena_pace.o"])
        link_file.libs=subprocess.check_output(["/sbin/ldconfig","-p"],text=True).splitlines()
        names=work/"libs";names.mkdir()
        binary=link_file([*read(objdir/"link.json"),"-lcrypto"],"bot",objdir,names)
        gns=objdir/"GameNetworkingSockets/lib/libGameNetworkingSockets.so"
        check(sha(gns)==parent["gns_sha256"],"GNS mismatch")
        result=dict(parent,transfer_receipt_sha256=TRANSFER_SHA,transfer_binary_sha256=parent["binary_sha256"],
                    custom_patch_sha256=sha(NATIVE/"red-custom.patch"),custom_source_sha256=sha(NATIVE/"red_custom.h"),
                    custom_builder_sha256=sha(Path(__file__)),binary_sha256=sha(binary),rebuilt_objects=rebuilt,
                    dependencies=dict(sorted(deps.items())),toolchain={tool:subprocess.check_output([tool,"--version"],text=True).splitlines()[0]
                                                     for tool in ("cc","c++","ld","objcopy")})
        data=(json.dumps(result,indent=2)+"\n").encode()
        pin=NATIVE/"red-custom-build.json"
        if pin.exists():check(pin.read_bytes()==data,"Custom image differs from frozen build")
        out.mkdir(parents=True);shutil.copy2(binary,out/"jk-bot-client");shutil.copy2(gns,out/gns.name)
        (out/"red-custom-build.json").write_bytes(data)
        print(result["binary_sha256"],out)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--red-export",required=True,type=Path)
    parser.add_argument("--globals-header",required=True,type=Path)
    parser.add_argument("--source",required=True,action="append",type=Path)
    parser.add_argument("--output",required=True,type=Path)
    build(parser.parse_args())
