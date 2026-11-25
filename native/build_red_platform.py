"""Rebuild the supported-platform bot as a verified child of the frozen custom client."""
import argparse
import difflib
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

NATIVE = Path(__file__).resolve().parent
CUSTOM_RECEIPT = "9b7218b9d0f7ec8018b88a1a8fd1eacd135e255fa4f033b984eed813a10cf4e1"
BUILD_INPUTS = ("build_red_custom.py", "build_red_policy.py", "build_arena_pace.py",
                "build_planner_go.py", "arena_pace.c", "red_policy.inc", "red-policy.patch",
                "red_transfer.inc", "red-transfer.patch", "red_nav_recall.h",
                "red-transfer-build.json", "red_custom.h")


def digest(file):
    return hashlib.sha256(file.read_bytes()).hexdigest()


def build(args):
    receipt = NATIVE / "red-custom-build.json"
    if digest(receipt) != CUSTOM_RECEIPT:
        raise ValueError("Unexpected custom parent")
    parent = json.loads(receipt.read_bytes())
    for name, key in (("red-custom.patch", "custom_patch_sha256"), ("red_custom.h", "custom_source_sha256"),
                      ("build_red_custom.py", "custom_builder_sha256")):
        if digest(NATIVE / name) != parent[key]:
            raise ValueError("Unexpected parent input " + name)
    out = args.output.resolve()
    if out.exists() or any((part / ".git").exists() for part in (out, *out.parents)):
        raise ValueError("Use fresh external output")
    # Use the frozen build recipe verbatim and apply the additional source after its original patch.
    with tempfile.TemporaryDirectory(prefix="adjoin-supported-platform-") as folder:
        work = Path(folder)
        for name in BUILD_INPUTS:
            shutil.copyfile(NATIVE / name, work / name)
        extra = NATIVE / "red-platform.patch"
        inc = NATIVE / "red_platform.inc"
        add_file = "".join(difflib.unified_diff([], inc.read_text().splitlines(True), "/dev/null", "b/src/AI/red_platform.inc"))
        (work / "red-custom.patch").write_bytes((NATIVE / "red-custom.patch").read_bytes() + extra.read_bytes() + add_file.encode())
        built = work / "images"
        cmd = [sys.executable, "-B", work / "build_red_custom.py", "--red-export", args.red_export,
               "--globals-header", args.globals_header, "--output", built]
        for source in args.source:
            cmd.extend(("--source", source))
        subprocess.run(cmd, check=True)
        current = json.loads((built / "red-custom-build.json").read_bytes())
        for unit, sha in parent["rebuilt_objects"].items():
            if unit != "AI/jkBot" and current["rebuilt_objects"][unit] != sha:
                raise ValueError("Unexpected changed object " + unit)
        result = dict(current, custom_receipt_sha256=CUSTOM_RECEIPT, custom_binary_sha256=parent["binary_sha256"],
                      custom_patch_sha256=parent["custom_patch_sha256"], platform_patch_sha256=digest(extra),
                      platform_builder_sha256=digest(Path(__file__)), platform_source_sha256=digest(inc))
        raw = (json.dumps(result, indent=2) + "\n").encode()
        pin = NATIVE / "red-platform-build.json"
        if pin.exists() and raw != pin.read_bytes():
            raise ValueError("Unexpected platform image or receipt")
        out.mkdir(parents=True)
        for name in ("jk-bot-client", "libGameNetworkingSockets.so"):
            shutil.copy2(built / name, out / name)
        (out / "red-platform-build.json").write_bytes(raw)
        print(result["binary_sha256"], out)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--red-export", required=True, type=Path)
    parser.add_argument("--globals-header", required=True, type=Path)
    parser.add_argument("--source", required=True, action="append", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    build(parser.parse_args())
