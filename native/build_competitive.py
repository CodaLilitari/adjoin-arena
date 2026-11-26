"""Reproduce the native competitive client on the pinned Red transfer build."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from build_arena_pace import check, read, sha

NATIVE = Path(__file__).resolve().parent
PARENT_SHA = "305606479cb89d790305aae378aad8130a40ff519e479e40ca0d78c014a23849"
OVERLAYS = ("saber-combat.patch", "competitive-light-profile.patch")


def build(args):
    out = args.output.resolve()
    sources = [args.red_export.resolve(), NATIVE.parent, *[p.resolve() for p in args.source]]
    check(not out.exists() and not any((p / ".git").exists() for p in (out, *out.parents))
          and not any(p == out or p in out.parents for p in sources), "Fresh external output required")
    parent_file = NATIVE / "red-transfer-build.json"
    check(sha(parent_file) == PARENT_SHA, "Wrong frozen Red transfer receipt")
    parent = read(parent_file)
    pins = {"build_red_transfer.py": "transfer_builder_sha256", "red-transfer.patch": "transfer_patch_sha256",
            "red_transfer.inc": "transfer_source_sha256", "red_nav_recall.h": "nav_recall_sha256"}
    for name, key in pins.items():
        check(sha(NATIVE / name) == parent[key], "Wrong transfer input: " + name)
    with tempfile.TemporaryDirectory(prefix="adjoin-competitive-") as tmp:
        stage = Path(tmp) / "native"
        stage.mkdir()
        for name in ("reproduce_red_build.py", "build_red_transfer.py", "build_red_policy.py",
                     "build_arena_pace.py", "build_planner_go.py", "red-policy-build.json",
                     "red-policy.patch", "red_policy.inc", "pace-build.json", "planner-go-build.json",
                     "arena_pace.c", "red_transfer.inc", "red_nav_recall.h"):
            shutil.copyfile(NATIVE / name, stage / name)
        # The frozen transfer builder first applies Red's tactics, then the
        # policy and transfer patches. Extend that last patch in order.
        (stage / "red-transfer.patch").write_bytes(b"".join(
            (NATIVE / name).read_bytes().rstrip(b"\n") + b"\n" for name in ("red-transfer.patch", *OVERLAYS)))
        built = Path(tmp) / "built"
        command = [sys.executable, "-B", stage / "reproduce_red_build.py", "transfer",
                   "--red-export", args.red_export.resolve(), "--globals-header", args.globals_header.resolve(),
                   "--output", built]
        for source in args.source:
            command.extend(("--source", source.resolve()))
        subprocess.run(command, check=True)
        receipt = read(built / "red-transfer-build.json")
        receipt.update(composed_transfer_patch_sha256=receipt["transfer_patch_sha256"],
                       transfer_patch_sha256=parent["transfer_patch_sha256"], transfer_receipt_sha256=PARENT_SHA,
                       transfer_binary_sha256=parent["binary_sha256"], competitive_builder_sha256=sha(Path(__file__)),
                       competitive_overlays={name: sha(NATIVE / name) for name in OVERLAYS})
        data = (json.dumps(receipt, indent=2) + "\n").encode()
        retained = NATIVE / "competitive-build.json"
        if retained.exists():
            check(data == retained.read_bytes(), "Competitive rebuild differs from retained receipt")
        out.mkdir(parents=True)
        for name in ("jk-bot-client", "libGameNetworkingSockets.so"):
            shutil.copy2(built / name, out / name)
        (out / retained.name).write_bytes(data)
        print(receipt["binary_sha256"], out)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--red-export", required=True, type=Path)
    parser.add_argument("--source", required=True, action="append", type=Path)
    parser.add_argument("--globals-header", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    build(parser.parse_args())
