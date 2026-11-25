"""Rebuild the optional Linux planner-GO client using verified source, headers and packaged link objects.

Supply a pinned, bot-patched engine source and its generated globals.h; optionally
supply --source multiple times for verified source snapshots. All outputs go to
a new directory outside the engine and game-server repositories.
"""
import argparse
import ctypes.util
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tarfile
import tempfile


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check(condition, message):
    if not condition:
        raise ValueError(message)


def read_pinned_sources(repo, roots, dst, manifest):
    # A few upstream working copies have CRLF checkouts. The build consumes the
    # exact LF source bytes hashed in BOT_BUILD.json, including the bot driver.
    additions = {}
    member = None
    for line in (repo / "native/bot-client.patch").read_text().splitlines():
        if line.startswith("diff --git "):
            member = None
        elif line.startswith("+++ b/"):
            member = line[6:]
            additions[member] = []
        elif member and line.startswith("+"):
            additions[member].append(line[1:])
    for name, expected in manifest["compiled_sources"].items():
        candidates = [p.read_bytes().replace(b"\r\n", b"\n") for root in roots if (p := root / name).is_file()]
        if name in additions:
            candidates.append(("\n".join(additions[name]) + "\n").encode())
        data = next((s for s in candidates if hashlib.sha256(s).hexdigest() == expected), None)
        check(data is not None, f"Missing pinned source: {name}")
        path = dst / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def build(args):
    repo, output = Path(__file__).resolve().parents[1], args.output.resolve()
    roots = [p.resolve() for p in args.source]
    check(all(output != path and path not in output.parents and output not in path.parents
              for path in [repo, *roots]), "Use a fresh output directory outside the checkout and source trees")
    check(not any((p / ".git").exists() for p in [output, *output.parents]), "Choose an output outside Git")
    output.mkdir(exist_ok=False, parents=True)
    manifest = json.loads((repo / "native/BOT_BUILD.json").read_text())
    archive = repo / "native/bot-relink-linux-x86_64.tar.gz"
    patch = repo / "native/planner-go.patch"
    check(sha(archive) == manifest["files"]["native/bot-relink-linux-x86_64.tar.gz"]["sha256"], "Wrong relink archive")
    base_patch = repo / "native/bot-client.patch"
    check(sha(base_patch) == manifest["files"]["native/bot-client.patch"]["sha256"], "Wrong upstream bot patch")
    check(sha(args.globals_header) == "edec9732ccad1f32d9fe4740ca17fdb76a05459181b196c779dbe45519a00e78",
          "Unexpected generated globals.h")
    with tempfile.TemporaryDirectory(prefix="adjoin-planner-") as tmp:
        work = Path(tmp)
        src, link_dir, inc = work / "source", work / "link", work / "generated"
        read_pinned_sources(repo, roots, src, manifest)
        subprocess.run(["patch", "--batch", "--fuzz=0", "-p1", "-i", str(patch)], cwd=src, check=True)
        inc.mkdir()
        shutil.copyfile(args.globals_header, inc / "globals.h")
        with tarfile.open(archive) as f:
            f.extractall(link_dir, filter="data")
        for name, expected in manifest["relink_inputs"].items():
            check(sha(link_dir / name) == expected, f"Invalid relink input: {name}")
        obj = link_dir / "CMakeFiles/sith_engine.dir/src/AI/jkBot.c.o"
        flags = ["-std=gnu11", "-O3", "-DNDEBUG", "-fshort-wchar", "-DARCH_64BIT", "-DLINUX",
                 "-DNO_JK_MMAP", "-DPLATFORM_LINUX", "-DPLATFORM_POSIX", "-DPLATFORM_GNS",
                 "-DPLATFORM_CURL", "-DPLATFORM_NO_CACERT_BLOB", "-DQOL_IMPROVEMENTS", "-DSDL2_RENDER",
                 "-DSTDSOUND_OPENAL", "-DTARGET_CAN_JKGM", "-D_XOPEN_SOURCE=500", "-D_DEFAULT_SOURCE",
                 "-D_FORTIFY_SOURCE=3", "-fstack-protector-strong", "-fstack-clash-protection",
                 "-fcf-protection", "-Werror=implicit-function-declaration"]
        subprocess.run(["cc", *flags, "-I"+str(src/"src"), "-I"+str(inc), "-MMD", "-MF", str(work/"inputs.d"),
                        "-c", str(src/"src/AI/jkBot.c"), "-o", str(obj)], check=True)
        headers = shlex.split((work/"inputs.d").read_text().replace("\\\n"," ").split(":",1)[1])
        changed = sorted({Path(v).relative_to(src).as_posix() for v in headers if Path(v).is_relative_to(src)
                          and sha(Path(v)) != manifest["compiled_sources"][Path(v).relative_to(src).as_posix()]})
        link = json.loads((link_dir / "link.json").read_text())
        libs = subprocess.check_output(["/sbin/ldconfig", "-p"], text=True).splitlines()
        names = work / "system-link-names"
        names.mkdir()
        for option in sorted(set(link)):
            if not re.fullmatch(r"-l[\w.+-]+", option):
                continue
            soname = ctypes.util.find_library(option[2:])
            real = next((line.split(" => ")[1] for line in libs if line.split()[0] == soname and "x86-64" in line), None)
            if real:
                (names / ("lib"+option[2:]+".so")).symlink_to(real)
        subprocess.run(link, cwd=link_dir, env=dict(os.environ, LIBRARY_PATH=str(names)), check=True)
        binary = output / "jk-bot-client"
        gns = output / "libGameNetworkingSockets.so"
        shutil.copy2(link_dir / "jk-bot-client-relinked", binary)
        shutil.copy2(link_dir / "GameNetworkingSockets/lib/libGameNetworkingSockets.so", gns)
        check(sha(gns) == manifest["files"]["bin/bots-linux-x86_64/libGameNetworkingSockets.so"]["sha256"],
              "Linked GNS differs from distributed GNS")
        receipt = dict(schema=1, source_commit=manifest["base_commit"], patch="native/planner-go.patch",
                       binary_sha256=sha(binary), gns_sha256=sha(gns), patch_sha256=sha(patch),
                       base_binary_sha256=manifest["files"]["bin/bots-linux-x86_64/jk-bot-client"]["sha256"],
                       base_patch_sha256=sha(base_patch), relink_archive_sha256=sha(archive),
                       generated_globals_sha256=sha(args.globals_header), patched_sources={n:sha(src/n) for n in changed},
                       rebuilt_object_sha256=sha(obj), compile_flags=flags,
                       toolchain={tool:subprocess.check_output([tool, "--version"], text=True).splitlines()[0]
                                  for tool in ("cc", "c++", "ld")})
        (output/"planner-build.json").write_text(json.dumps(receipt, indent=2)+"\n")
        accepted = json.loads((repo/"native/planner-go-build.json").read_text())
        check(receipt == accepted, "Retained new build receipt differs from the qualified toolchain or output")
        print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, action="append", type=Path)
    parser.add_argument("--globals-header", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    build(parser.parse_args())
