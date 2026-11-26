#!/usr/bin/env python3
"""Package a compiled current JKWeb bot with its patch and LGPL relink inputs."""
from pathlib import Path
import argparse
import gzip
import hashlib
import io
import json
import shlex
import shutil
import subprocess
import sys
import tempfile
import tarfile

from engine_patches import BASE, PATCHES, run_git, staged_source
SDK = "6.0.12"
ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def package(source, build, base_repo=None, output_root=ROOT):
    # Verify the isolated bundle before replacing a distributable or its receipt.
    with tempfile.TemporaryDirectory(prefix="adjoin-web-package-") as tmp:
        stage = Path(tmp)
        _prepare(source, build, base_repo or source, stage)
        for name in ("bin/bots-jkweb/openjkdf2.js", "bin/bots-jkweb/openjkdf2.wasm",
                     "web_bots/engine-relink.tar.gz", "web_bots/BUILD.json"):
            target = output_root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as stream:
                replacement = Path(stream.name)
            try:
                shutil.copyfile(stage / name, replacement)
                replacement.chmod(0o644)
                replacement.replace(target)
            finally:
                replacement.unlink(missing_ok=True)


def _prepare(source, build, base_repo, stage):
    changed = staged_source(source, base_repo)
    patches = [ROOT / "web_bots" / name for name in PATCHES]
    # In a normal checkout also rule out unrelated tracked modifications.
    if (source / ".git").exists():
        changed_in_git = set(run_git(source, "diff", "--name-only", "HEAD", "--ignore-submodules=all").decode().splitlines())
        if changed_in_git.difference(changed):
            raise ValueError("Unrelated modified source in the engine checkout")
    libs = ("lib/libpng", "lib/zlib")
    pins = {}
    for line in run_git(base_repo, "ls-tree", BASE, "--", *libs).decode().splitlines():
        attrs, name = line.split("\t")
        mode, kind, commit = attrs.split()
        if mode != "160000" or kind != "commit":
            raise ValueError("Unexpected source dependency " + name)
        pins[name] = commit
    if set(pins) != set(libs):
        raise ValueError("Pinned source dependency missing")
    for name, commit in pins.items():
        directory = source / name
        if (directory / ".git").exists() and run_git(directory, "rev-parse", "HEAD").decode().strip() != commit:
            raise ValueError("Wrong dependency checkout: " + name)
    out = stage / "bin/bots-jkweb"
    out.mkdir(parents=True, exist_ok=True)
    for name in ("openjkdf2.js", "openjkdf2.wasm"):
        shutil.copy2(build / name, out / name)
    link = shlex.split((build / "CMakeFiles/openjkdf2.dir/link.txt").read_text())
    expanded = []
    for arg in link[1:]:
        if arg.startswith("@"):
            expanded.extend(shlex.split((build / arg[1:]).read_text()))
        else:
            expanded.append(arg)
    members = {}
    relink = ["em++"]
    object_files = []
    prefix_flags = ("-ffile-prefix-map=", "-fmacro-prefix-map=")
    for arg in expanded:
        path = Path(arg)
        if arg.startswith(("-L", *prefix_flags)):
            continue
        if path.is_absolute():
            if path.parent == source / "packaging/wasm":
                arg = "pre-js/" + path.name
                members[arg] = path
            else:
                raise ValueError("Unexpected absolute linker input: " + arg)
        elif path.suffix in (".o", ".obj", ".a"):
            if ".." in path.parts or not (build / arg).is_file():
                raise ValueError("Missing linker input: " + arg)
            members[arg] = build / arg
            if path.suffix in (".o", ".obj"):
                object_files.append(arg)
        relink.append(arg)
    smacker_objects = {}
    for name in ("smacker", "smk_bitstream", "smk_hufftree"):
        paths = [path for path in object_files
                 if Path(path).parent.name == "libsmacker" and Path(path).stem == name + ".c"]
        if len(paths) != 1:
            raise ValueError("Expected one linked libsmacker object for " + name)
        smacker_objects[name + ".c"] = paths[0]
    for file in (source / "src/external/libsmacker").iterdir():
        if file.is_file():
            members["libsmacker/" + file.name] = file
    for name in ("engine_config.h", "types_enums.h"):
        members["libsmacker/" + name] = source / "src" / name
    members["ENGINE_LICENSE.md"] = source / "LICENSE.md"
    compiler_flags = {}
    for row in (build / "CMakeFiles/sith_engine.dir/flags.make").read_text().splitlines():
        if " = " in row:
            key, value = row.split(" = ", 1)
            compiler_flags[key] = shlex.split(value)
    compile_args = compiler_flags["C_DEFINES"] + [
        flag for flag in compiler_flags["C_FLAGS"] if not flag.startswith(prefix_flags)] + ["-Ilibsmacker"]
    # Bundled assertions contain the compiler's __FILE__ string. Re-create that
    # logical filename when the source is unpacked under a different directory.
    logical_source = str(source / "src/external/libsmacker")
    for flag in compiler_flags["C_FLAGS"]:
        if flag.startswith(prefix_flags):
            old, new = flag.split("=", 1)[1].split("=", 1)
            if logical_source.startswith(old):
                logical_source = new + logical_source[len(old):]
    compile_args.append("-ffile-prefix-map=libsmacker=" + logical_source)
    script = '''#!/usr/bin/env python3
"""Activate Emscripten 6.0.12, modify libsmacker, then run this script."""
from pathlib import Path
import json, subprocess
root = Path(__file__).resolve().parent
config = json.loads((root / "link.json").read_text())
for source, linked_object in config["smacker_objects"].items():
    subprocess.run(["emcc", *config["compile_args"], "-c", "libsmacker/" + source,
                    "-o", linked_object], cwd=root, check=True)
subprocess.run(config["link"], cwd=root, check=True)
print(root / "openjkdf2.wasm")
'''
    archive = stage / "web_bots/engine-relink.tar.gz"
    archive.parent.mkdir(parents=True, exist_ok=True)
    generated = {"relink.py": script.encode(), "link.json": json.dumps(
        {"link": relink, "compile_args": compile_args, "smacker_objects": smacker_objects}, indent=2).encode()}
    # Host ownership, tool time and temporary absolute paths must not affect archive bytes.
    with archive.open("wb") as output, gzip.GzipFile(filename="", mode="wb", fileobj=output, mtime=0) as gz:
        with tarfile.open(fileobj=gz, mode="w", format=tarfile.USTAR_FORMAT) as tar:
            for name in sorted(set(members) | set(generated)):
                data = generated[name] if name in generated else members[name].read_bytes()
                entry = tarfile.TarInfo(name)
                entry.size = len(data)
                entry.mode = 0o755 if name == "relink.py" else 0o644
                tar.addfile(entry, io.BytesIO(data))
    check = stage / "verify"
    with tarfile.open(archive) as tar:
        tar.extractall(check, filter="data")
    subprocess.run([sys.executable, "-B", "relink.py"], cwd=check, check=True)
    for name in ("openjkdf2.js", "openjkdf2.wasm"):
        if sha(check / name) != sha(out / name):
            raise ValueError("Recompiled libsmacker + relink differ from the source build: " + name)
    files = {p.relative_to(ROOT).as_posix(): p for p in patches}
    for path in (out / "openjkdf2.js", out / "openjkdf2.wasm", archive):
        files[path.relative_to(stage).as_posix()] = path
    manifest = {
        "repository": "https://github.com/tristamus/OpenJKDF2",
        "branch": "web-mp", "base_commit": BASE, "emscripten": SDK,
        "netcode": 2, "game": "JKDF2", "game_assets_included": False,
        "method": "CMake source build with ordinary player input hooks; unchanged upstream WSRelay protocol.",
        "patch": "web_bots/engine.patch",
        "patches": ["web_bots/" + name for name in PATCHES],
        "verify_recompiled_libsmacker": True, "relink": "web_bots/engine-relink.tar.gz",
        "source_pins": [f" {commit} {name} ({commit[:7]})" for name, commit in sorted(pins.items())],
        "relink_check": {"objects": len(object_files), "recompiled": list(smacker_objects),
                         "byte_identical": ["openjkdf2.js", "openjkdf2.wasm"]},
        "changed_sources": changed,
        "files": {name: {"sha256": sha(p), "bytes": p.stat().st_size} for name, p in files.items()},
    }
    (stage / "web_bots/BUILD.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest["files"], indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("build", type=Path)
    parser.add_argument("--base-repo", type=Path, help="Pinned Git reference for a separately verified exported source tree")
    parser.add_argument("--output-root", type=Path, default=ROOT, help="Publish verified JS/WASM and relink receipt here")
    args = parser.parse_args()
    package(args.source.resolve(), args.build.resolve(), args.base_repo.resolve() if args.base_repo else None,
            args.output_root.resolve())
