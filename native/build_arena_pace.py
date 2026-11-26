"""Build the opt-in Linux host and planner-GO client with the same 34-ms game clock."""
import argparse
import ctypes.util
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile

from build_planner_go import check, read_pinned_sources

NATIVE = Path(__file__).resolve().parent
REPO = NATIVE.parent
HOOKS = {
    "Gameplay/sithTime": {"stdPlatform_GetTimeMsec": "arena_clock_ms", "Linux_TimeUs": "arena_clock_us"},
    "Main/jkMain": {"jkPlayer_fpslimit": "arena_uncapped_fps"},
    "Main/sithMain": {"sithTime_Advance": "arena_advance"},
    "Win95/Window": {"SDL_Delay": "arena_window_delay"},
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text())


def run(argv, **kw):
    return subprocess.run(argv, check=True, **kw)


def planner_object(args, work, bot_object, manifest):
    old = read(NATIVE / "planner-go-build.json")
    check(sha(NATIVE / "planner-go.patch") == old["patch_sha256"], "Invalid planner patch")
    check(sha(args.globals_header) == old["generated_globals_sha256"], "Invalid generated globals")
    src = work / "src-tree"
    read_pinned_sources(REPO, args.source, src, manifest)
    run(["patch", "--batch", "--fuzz=0", "-p1", "-i", str(NATIVE / "planner-go.patch")], cwd=src)
    for name, digest in old["patched_sources"].items():
        check(sha(src / name) == digest, f"Wrong planner source {name}")
    gen = work / "generated"
    gen.mkdir()
    shutil.copyfile(args.globals_header, gen / "globals.h")
    run(["cc", *old["compile_flags"], "-I"+str(src/"src"), "-I"+str(gen), "-c",
         str(src/"src/AI/jkBot.c"), "-o", str(bot_object)])
    check(sha(bot_object) == old["rebuilt_object_sha256"], "Rebuilt planner object differs from prior 1x")
    return old


def link_file(link, name, objects, lib_names):
    for opt in sorted(set(link)):
        if not re.fullmatch(r"-l[\w.+-]+", opt):
            continue
        alias = lib_names / ("lib" + opt[2:] + ".so")
        if alias.exists():
            continue
        soname = ctypes.util.find_library(opt[2:])
        dest = next((s.rsplit(" => ", 1)[-1] for s in link_file.libs
                     if s.strip().startswith(str(soname) + " ") and "x86-64" in s), None)
        if dest:
            alias.symlink_to(dest)
    run([*link, "arena_pace.o"], cwd=objects, env=dict(os.environ, LIBRARY_PATH=str(lib_names)))
    output = objects / link[link.index("-o") + 1]
    if name == "host":
        for cmd in read(objects / "post-link.json"):
            run(cmd, cwd=objects)
    return output


def build(args):
    out = args.output.resolve()
    check(all(not (p / ".git").exists() for p in (out, *out.parents)), "Output must be outside Git")
    check(all(out != p.resolve() and p.resolve() not in out.parents
              for p in [REPO, *args.source]), "Output must be outside the sources")
    check(not out.exists(), "Use a fresh output directory")
    out.parent.mkdir(parents=True, exist_ok=True)
    source = NATIVE / "arena_pace.c"
    receipt = dict(schema=1, step_ms=34, rates=[0, 1, 2, 4, 8, 16, 32], pace_source_sha256=sha(source),
                   builder_sha256=sha(Path(__file__)), hooks=HOOKS, toolchain={})
    for name in ("cc", "c++", "ld", "objcopy"):
        receipt["toolchain"][name] = subprocess.check_output([name, "--version"],text=True).splitlines()[0]
    with tempfile.TemporaryDirectory(prefix="adjoin-pace-") as tmp:
        scratch = Path(tmp)
        artifacts = scratch / "built"
        artifacts.mkdir()
        lib_names = scratch / "link-names"
        lib_names.mkdir()
        link_file.libs = subprocess.check_output(["/sbin/ldconfig", "-p"], text=True).splitlines()
        for name, executable, manifest_name, archive_name, bin_subdir in (
            ("host", "openjkdf2", "BUILD", "relink-linux-x86_64.tar.gz", "linux-x86_64"),
            ("bot", "jk-bot-client", "BOT_BUILD", "bot-relink-linux-x86_64.tar.gz", "bots-linux-x86_64"),
        ):
            work = scratch / name
            objects = work / "link"
            objects.mkdir(parents=True)
            manifest = read(NATIVE / (manifest_name + ".json"))
            archive = NATIVE / archive_name
            archive_sha = sha(archive)
            check(archive_sha == manifest["files"]["native/" + archive_name]["sha256"], "Wrong relink archive")
            with tarfile.open(archive) as f:
                f.extractall(objects, filter="data")
            for rel, expected in manifest["relink_inputs"].items():
                check(sha(objects/rel) == expected, f"Wrong original link input {rel}")
            target = f"bin/{bin_subdir}/{executable}"
            base_binary = manifest["files"][target]["sha256"]
            check(sha(REPO / target) == base_binary, "Base runtime differs from its original receipt")
            info = dict(archive_sha256=archive_sha, base_binary_sha256=base_binary)
            engine = objects / "CMakeFiles/sith_engine.dir/src"
            if name == "bot":
                old = planner_object(args, work, engine / "AI/jkBot.c.o", manifest)
                info.update(base_binary_sha256=old["binary_sha256"], planner_object_sha256=old["rebuilt_object_sha256"])
            for filename, hooks in HOOKS.items():
                obj = engine / (filename + ".c.o")
                refs = {line.split()[-1] for line in subprocess.check_output(["nm", "-u", obj], text=True).splitlines()}
                check(set(hooks) <= refs, f"Missing engine calls in {filename}: {set(hooks) - refs}")
                rename = [piece for old, new in hooks.items() for piece in ("--redefine-sym", old+"="+new)]
                run(["objcopy", *rename, obj])
            run(["cc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", "-fPIC", "-c", source,
                 "-o", objects/"arena_pace.o"])
            binary = link_file(read(objects/"link.json"), name, objects, lib_names)
            dest = artifacts / name
            dest.mkdir()
            shutil.copy2(binary, dest/executable)
            gns = objects/"GameNetworkingSockets/lib/libGameNetworkingSockets.so"
            check(sha(gns) == manifest["files"][f"bin/{bin_subdir}/libGameNetworkingSockets.so"]["sha256"], "Wrong GNS")
            shutil.copy2(gns, dest/"libGameNetworkingSockets.so")
            receipt[name] = dict(info, binary_sha256=sha(binary), gns_sha256=sha(gns))
        receipt_file = artifacts / "pace-build.json"
        receipt_file.write_text(json.dumps(receipt, indent=2)+"\n", encoding="utf-8")
        pin = NATIVE / "pace-build.json"
        if pin.is_file():
            check(receipt_file.read_bytes() == pin.read_bytes(), "Pace build differs from retained receipt")
        shutil.copytree(artifacts, out)
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--source", required=True, action="append", type=Path)
    p.add_argument("--globals-header", required=True, type=Path)
    build(p.parse_args())
