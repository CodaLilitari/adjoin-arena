"""Link the verified competitive controller to the original native engine clock."""
import argparse
import ctypes.util
import gzip
import io
import json
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile

from build_arena_pace import check, link_file, read, read_pinned_sources, run, sha
from build_competitive import NATIVE, OVERLAYS

NOBLE_LIBM = "4e7324196b5d12cc5040d71b17fefb9891d103611f5e66debc7225d1884b0505"


def relink_bundle(original, objects, destination):
    """Retain the original distributable member list and the two rebuilt playing objects."""
    with tarfile.open(original) as source, destination.open("wb") as f:
        with gzip.GzipFile(filename="", fileobj=f, mode="wb", mtime=0) as gz, tarfile.open(fileobj=gz, mode="w|") as out:
            for member in source:
                if member.name == "link.json":
                    data = (json.dumps([*read(objects / "link.json"), "-lcrypto", "-lm"], indent=2) + "\n").encode()
                    member.size = len(data)
                    out.addfile(member, io.BytesIO(data))
                elif member.isfile():
                    file = objects / member.name
                    member.size = file.stat().st_size
                    with file.open("rb") as data:
                        out.addfile(member, data)
                else:
                    out.addfile(member)


def build(args):
    out = args.output.resolve()
    release = args.red_export.resolve()
    sources = [p.resolve() for p in args.source]
    check(not out.exists() and not any((p / ".git").exists() for p in (out, *out.parents))
          and not any(p == out or p in out.parents for p in (NATIVE.parent, release, *sources)),
          "Fresh external output required")
    controller = NATIVE / "competitive-build.json"
    parent = read(controller)
    libm = args.target_libm.resolve()
    check(sha(libm) == NOBLE_LIBM, "Expected Ubuntu 24.04 amd64 libc6 2.39-0ubuntu8 libm.so.6")
    archive = release / "native/bot-relink-linux-x86_64.tar.gz"
    overlay = release / "native/bot-tactics.patch"
    check(sha(archive) == parent["archive_sha256"] and sha(overlay) == parent["red_overlay_sha256"]
          and sha(args.globals_header) == parent["generated_globals_sha256"], "Wrong engine inputs")
    manifest = read(release / "native/BOT_BUILD.json")
    with tempfile.TemporaryDirectory(prefix="adjoin-stock-clock-") as tmp:
        work = Path(tmp)
        src, objects, includes = work / "source", work / "objects", work / "generated"
        read_pinned_sources(release, sources, src, manifest)
        for file in (overlay, *[NATIVE / name for name in ("red-policy.patch", "red-transfer.patch", *OVERLAYS)]):
            run(["patch", "--quiet", "--batch", "--fuzz=0", "-p1", "-i", file], cwd=src)
        for name in ("red_policy.inc", "red_transfer.inc", "red_nav_recall.h"):
            shutil.copyfile(NATIVE / name, src / "src/AI" / name)
        for name, digest in parent["dependencies"].items():
            check(sha(src / name) == digest, "Controller source mismatch: " + name)
        includes.mkdir()
        shutil.copyfile(args.globals_header, includes / "globals.h")
        with tarfile.open(archive) as f:
            f.extractall(objects, filter="data")
        for name, digest in manifest["relink_inputs"].items():
            check(sha(objects / name) == digest, "Invalid archived object: " + name)
        for unit, digest in parent["rebuilt_objects"].items():
            source = src / "src" / (unit + ".c")
            obj = objects / "CMakeFiles/sith_engine.dir/src" / (unit + ".c.o")
            fixed = [f"-fmacro-prefix-map={source}=/tmp/adjoin-red-fj8jyjnc/source/src/Devices/sithControl.c"
                     ] if unit == "Devices/sithControl" else []
            run(["cc", *parent["flags"], *fixed, "-I" + str(src / "src"), "-I" + str(includes),
                 "-c", source, "-o", obj])
            check(sha(obj) == digest, "Playing object differs from the tested build: " + unit)
        # The frozen linker includes this member; an empty translation unit
        # leaves every stock clock reference in the original engine objects intact.
        run(["cc", "-x", "c", "-c", "/dev/null", "-o", objects / "arena_pace.o"])
        lib_names = work / "libs"
        lib_names.mkdir()
        (lib_names / "libm.so").symlink_to(libm)
        link_file.libs = subprocess.check_output(["/sbin/ldconfig", "-p"], text=True).splitlines()
        command = []
        for name in [*read(objects / "link.json"), "-lcrypto", "-lm"]:
            if re.fullmatch(r"-l[\w.+-]+", name):
                soname = ctypes.util.find_library(name[2:])
                check(soname and (libm.parent / soname).is_file(), "Missing target runtime library for " + name)
                command.append(str(libm.parent / soname))
            else:
                command.append(name)
        command.extend(["-Wl,-rpath-link," + str(libm.parent), str(libm.parent / "libstdc++.so.6"),
                        str(libm.parent / "libc.so.6"), str(libm.parent / "ld-linux-x86-64.so.2")])
        binary = link_file(command, "bot", objects, lib_names)
        versions = subprocess.check_output(["readelf", "--version-info", binary], text=True)
        glibc = max(tuple(map(int, v.split("."))) for v in re.findall(r"Name: GLIBC_([0-9.]+)", versions))
        check(glibc <= (2, 39), "Result requires a newer glibc than Ubuntu 24.04")
        library = objects / "GameNetworkingSockets/lib/libGameNetworkingSockets.so"
        check(sha(library) == parent["gns_sha256"], "Wrong networking library")
        bundle = work / "competitive-relink-linux-x86_64.tar.gz"
        relink_bundle(archive, objects, bundle)
        receipt = dict(competitive_receipt_sha256=sha(controller), builder_sha256=sha(Path(__file__)),
                       binary_sha256=sha(binary), gns_sha256=sha(library), clock="original engine clock",
                       rebuilt_objects=parent["rebuilt_objects"], target_libm_sha256=NOBLE_LIBM,
                       required_glibc=".".join(map(str, glibc)), relink_sha256=sha(bundle))
        data = (json.dumps(receipt, indent=2) + "\n").encode()
        retained = NATIVE / "competitive-stock-build.json"
        if retained.exists():
            check(data == retained.read_bytes(), "Native stock-clock build differs from retained receipt")
        out.mkdir(parents=True)
        shutil.copy2(bundle, out / bundle.name)
        shutil.copy2(binary, out / "jk-bot-client")
        shutil.copy2(library, out / library.name)
        (out / retained.name).write_bytes(data)
        print(receipt["binary_sha256"], out)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--red-export", required=True, type=Path)
    parser.add_argument("--source", required=True, action="append", type=Path)
    parser.add_argument("--globals-header", required=True, type=Path)
    parser.add_argument("--target-libm", required=True, type=Path,
                        help="libm.so.6 extracted from Ubuntu 24.04 amd64 libc6 2.39-0ubuntu8")
    parser.add_argument("--output", required=True, type=Path)
    build(parser.parse_args())
