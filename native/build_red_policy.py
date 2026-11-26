"""Rebuild Red's complete PR3 tactics with a local neural decision and optional match pacing."""
import argparse
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tarfile
import tempfile

from build_arena_pace import HOOKS, check, link_file, read, read_pinned_sources, run, sha

NATIVE = Path(__file__).resolve().parent
RED_COMMIT = "f453778a3cf670dea43c44315786ae4afc8ae440"
RED_OVERLAY = "d378a01a5530e936388b370749af021bab32d53d6352369e8db8d5e106382a8d"
RED_BASE = "6950c859f9e82aca8285daac011e1b72cb2a57644f01d2a465987312100ac52d"
RED_ARCHIVE = "ca63beaa5c3a283639950be045df0d5ffa5a2fb39cc259db479c3deee4a4a123"


def build(args):
    out, release = args.output.resolve(), args.red_export.resolve()
    roots = [p.resolve() for p in args.source]
    check(not out.exists() and all(not (p/".git").exists() for p in (out,*out.parents)),
          "Use a fresh external build directory")
    check(all(p not in out.parents and p!=out for p in (release,NATIVE.parent,*roots)), "Output inside source")
    overlay, archive = release/"native/bot-tactics.patch", release/"native/bot-relink-linux-x86_64.tar.gz"
    base, policy, model = release/"native/bot-client.patch", NATIVE/"red-policy.patch", NATIVE/"red_policy.inc"
    manifest, flags = read(release/"native/BOT_BUILD.json"), read(NATIVE/"planner-go-build.json")["compile_flags"]
    check((sha(overlay),sha(base),sha(archive))==(RED_OVERLAY,RED_BASE,RED_ARCHIVE),"Wrong Red branch export")
    check(sha(args.globals_header)=="e700da5fb05eea91febcb0c6c9237573d29263125dfa9b195e3def0f0ea664e9",
          "Wrong generated globals.h")
    reference=release/"bin/bots-linux-x86_64/jk-bot-client"
    check(sha(reference)==manifest["files"]["bin/bots-linux-x86_64/jk-bot-client"]["sha256"],"Wrong base executable")
    pace=read(NATIVE/"pace-build.json")
    check(sha(NATIVE/"arena_pace.c")==pace["pace_source_sha256"] and HOOKS==pace["hooks"],"Pacing pins changed")
    with tempfile.TemporaryDirectory(prefix="adjoin-red-") as tmp:
        work=Path(tmp)
        src, objects, inc=work/"source",work/"link",work/"generated"
        inc.mkdir()
        shutil.copyfile(args.globals_header,inc/"globals.h")
        read_pinned_sources(release,roots,src,manifest)
        for patch in (overlay,policy):
            run(["patch","--batch","--fuzz=0","-p1","-i",str(patch)],cwd=src)
        shutil.copyfile(model,src/"src/AI/red_policy.inc")
        with tarfile.open(archive) as f:
            f.extractall(objects,filter="data")
        for rel, expected in manifest["relink_inputs"].items():
            check(sha(objects/rel)==expected,f"Wrong original link input {rel}")
        engine=objects/"CMakeFiles/sith_engine.dir/src"
        rebuilt={}
        dependencies={}
        for unit in ("AI/jkBot","Devices/sithControl"):
            obj=engine/(unit+".c.o")
            dep=work/"headers.d"
            run(["cc",*flags,"-I"+str(src/"src"),"-I"+str(inc),"-MMD","-MF",str(dep),
                 "-c",str(src/"src"/(unit+".c")),"-o",str(obj)])
            rebuilt[unit]=sha(obj)
            for name in shlex.split(dep.read_text().replace("\\\n"," ").split(":",1)[1]):
                p=Path(name)
                if p.is_relative_to(src): dependencies[p.relative_to(src).as_posix()]=sha(p)
        for name,hooks in HOOKS.items():
            obj=engine/(name+".c.o")
            refs={s.split()[-1] for s in subprocess.check_output(["nm","-u",obj],text=True).splitlines()}
            check(set(hooks)<=refs,f"Missing original timing calls in {name}")
            changes=[arg for old,new in hooks.items() for arg in ("--redefine-sym",old+"="+new)]
            run(["objcopy",*changes,obj])
        run(["cc","-std=c11","-O2","-Wall","-Wextra","-Werror","-fPIC","-c",NATIVE/"arena_pace.c",
             "-o",objects/"arena_pace.o"])
        link_file.libs=subprocess.check_output(["/sbin/ldconfig","-p"],text=True).splitlines()
        names=work/"link-names"; names.mkdir()
        binary=link_file([*read(objects/"link.json"),"-lcrypto"],"bot",objects,names)
        gns=objects/"GameNetworkingSockets/lib/libGameNetworkingSockets.so"
        check(sha(gns)==pace["bot"]["gns_sha256"] and sha(gns)==sha(reference.with_name(gns.name)),"Wrong GNS")
        info=dict(schema=1,base_commit=manifest["base_commit"],red_commit=RED_COMMIT,
            red_overlay_sha256=sha(overlay),base_patch_sha256=sha(base),archive_sha256=sha(archive),
            base_binary_sha256=sha(reference),binary_sha256=sha(binary),gns_sha256=sha(gns),
            policy_patch_sha256=sha(policy),policy_source_sha256=sha(model),builder_sha256=sha(Path(__file__)),
            pace_source_sha256=sha(NATIVE/"arena_pace.c"),pace_receipt_sha256=sha(NATIVE/"pace-build.json"),
            plan_gate=False,step_ms=34,rates=[1,2],generated_globals_sha256=sha(args.globals_header),
            flags=flags,rebuilt_objects=rebuilt,dependencies=dict(sorted(dependencies.items())),
            toolchain={tool:subprocess.check_output([tool,"--version"],text=True).splitlines()[0]
                       for tool in ("cc","c++","ld","objcopy")})
        receipt=(json.dumps(info,indent=2)+"\n").encode()
        pin=NATIVE/"red-policy-build.json"
        if pin.exists(): check(pin.read_bytes()==receipt,"Build differs from qualified Red recipe")
        out.mkdir(parents=True)
        shutil.copy2(binary,out/"jk-bot-client")
        shutil.copy2(gns,out/gns.name)
        (out/"red-policy-build.json").write_bytes(receipt)
        print(info["binary_sha256"],out)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source",required=True,action="append",type=Path)
    parser.add_argument("--red-export",required=True,type=Path)
    parser.add_argument("--globals-header",required=True,type=Path)
    parser.add_argument("--output",required=True,type=Path)
    build(parser.parse_args())
