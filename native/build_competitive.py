"""Recompile the playing and room-admission units on Red's pinned native engine."""
import argparse
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import tarfile
import tempfile

from build_arena_pace import HOOKS, check, link_file, read, read_pinned_sources, run, sha

NATIVE = Path(__file__).resolve().parent
PARENT_SHA = "305606479cb89d790305aae378aad8130a40ff519e479e40ca0d78c014a23849"
OVERLAYS = ("saber-combat.patch", "competitive-light-profile.patch", "navigation-memory.patch",
            "competitive-navigation.patch", "supported-ramp.patch", "navigation-observation.patch",
            "custom-episode.patch")
UNITS = ("AI/jkBot", "Devices/sithControl", "Gui/jkGUIMultiplayer")


def compile_controller(work, release, sources, globals_header):
    check(sha(NATIVE / "red-transfer-build.json") == PARENT_SHA, "Wrong Red transfer parent")
    parent = read(NATIVE / "red-transfer-build.json")
    pins = {"red-policy.patch": "policy_patch_sha256", "red_policy.inc": "policy_source_sha256",
            "red-transfer.patch": "transfer_patch_sha256", "red_transfer.inc": "transfer_source_sha256",
            "red_nav_recall.h": "nav_recall_sha256", "arena_pace.c": "pace_source_sha256"}
    for name, key in pins.items():
        check(sha(NATIVE / name) == parent[key], "Wrong Red source " + name)
    overlay = release / "native/bot-tactics.patch"
    archive = release / "native/bot-relink-linux-x86_64.tar.gz"
    check(sha(overlay) == parent["red_overlay_sha256"] and sha(archive) == parent["archive_sha256"]
          and sha(globals_header) == parent["generated_globals_sha256"], "Incorrect frozen engine inputs")
    manifest = read(release / "native/BOT_BUILD.json")
    src, objects, includes = work / "source", work / "objects", work / "generated"
    includes.mkdir()
    shutil.copyfile(globals_header, includes / "globals.h")
    read_pinned_sources(release, sources, src, manifest)
    for patch in (overlay, *(NATIVE / p for p in ("red-policy.patch", "red-transfer.patch", *OVERLAYS))):
        run(["patch", "--quiet", "--batch", "--fuzz=0", "-p1", "-i", patch], cwd=src)
    for name in ("red_policy.inc", "red_transfer.inc", "red_nav_recall.h"):
        shutil.copyfile(NATIVE / name, src / "src/AI" / name)
    with tarfile.open(archive) as bundle:
        bundle.extractall(objects, filter="data")
    for name, digest in manifest["relink_inputs"].items():
        check(sha(objects / name) == digest, "Incorrect input object " + name)
    engine = objects / "CMakeFiles/sith_engine.dir/src"
    rebuilt, dependencies = {}, {}
    for unit in UNITS:
        source = src / "src" / (unit + ".c")
        obj = engine / (unit + ".c.o")
        mapped = ("/tmp/adjoin-red-fj8jyjnc/source/src/Devices/sithControl.c"
                  if unit == "Devices/sithControl" else "/src/" + unit + ".c")
        dep = work / "headers.d"
        run(["cc", *parent["flags"], f"-fmacro-prefix-map={source}={mapped}",
             "-I" + str(src / "src"), "-I" + str(includes), "-MMD", "-MF", dep, "-c", source, "-o", obj])
        rebuilt[unit] = sha(obj)
        for name in shlex.split(dep.read_text().replace("\\\n", " ").split(":", 1)[1]):
            path = Path(name)
            if path.is_relative_to(src):
                dependencies[path.relative_to(src).as_posix()] = sha(path)
    check(rebuilt["Devices/sithControl"] == parent["rebuilt_objects"]["Devices/sithControl"], "Stock control changed")
    return parent, rebuilt, dict(sorted(dependencies.items()))


def build(args):
    out = args.output.resolve()
    sources = [p.resolve() for p in args.source]
    release = args.red_export.resolve()
    check(not out.exists() and not any((p / ".git").exists() for p in (out, *out.parents))
          and not any(p == out or p in out.parents or out in p.parents for p in (NATIVE.parent, release, *sources)),
          "Fresh external output required")
    with tempfile.TemporaryDirectory(prefix="adjoin-competitive-") as tmp:
        work = Path(tmp)
        parent, rebuilt, dependencies = compile_controller(work, release, sources, args.globals_header.resolve())
        objects = work / "objects"
        for unit, hooks in HOOKS.items():
            obj = objects / "CMakeFiles/sith_engine.dir/src" / (unit + ".c.o")
            refs = {line.split()[-1] for line in subprocess.check_output(["nm", "-u", obj], text=True).splitlines()}
            check(set(hooks) <= refs, "Missing stock clock hook " + unit)
            changes = [arg for old, new in hooks.items() for arg in ("--redefine-sym", old + "=" + new)]
            run(["objcopy", *changes, obj])
        run(["cc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", "-fPIC", "-c",
             NATIVE / "arena_pace.c", "-o", objects / "arena_pace.o"])
        libs = work / "libs"
        libs.mkdir()
        link_file.libs = subprocess.check_output(["/sbin/ldconfig", "-p"], text=True).splitlines()
        binary = link_file([*read(objects / "link.json"), "-lcrypto", "-lm"], "bot", objects, libs)
        library = objects / "GameNetworkingSockets/lib/libGameNetworkingSockets.so"
        check(sha(library) == parent["gns_sha256"], "Unexpected networking library")
        receipt = dict(parent, binary_sha256=sha(binary), rebuilt_objects=rebuilt, dependencies=dependencies,
                       transfer_receipt_sha256=PARENT_SHA, transfer_binary_sha256=parent["binary_sha256"],
                       competitive_builder_sha256=sha(Path(__file__)),
                       competitive_overlays={p: sha(NATIVE / p) for p in OVERLAYS},
                       toolchain={tool: subprocess.check_output([tool, "--version"], text=True).splitlines()[0]
                                  for tool in ("cc", "c++", "ld", "objcopy")})
        raw = (json.dumps(receipt, indent=2) + "\n").encode()
        retained = NATIVE / "competitive-build.json"
        if retained.exists():
            check(raw == retained.read_bytes(), "Competitive rebuild differs from retained receipt")
        out.mkdir(parents=True)
        shutil.copy2(binary, out / "jk-bot-client")
        shutil.copy2(library, out / library.name)
        (out / retained.name).write_bytes(raw)
        print(receipt["binary_sha256"], out)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--red-export", required=True, type=Path)
    parser.add_argument("--source", required=True, action="append", type=Path)
    parser.add_argument("--globals-header", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    build(parser.parse_args())

