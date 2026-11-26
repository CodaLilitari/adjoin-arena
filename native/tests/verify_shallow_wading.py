"""Stage the shared shallow-wading fix on the receipt-pinned native controller."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[2]
PATCH = ROOT / "web_bots/shallow-wading.patch"
SOURCE = "src/AI/jkBot.c"
PATCH_SHA = "5712e415aa58b162e008e30e5ae30ddca98d345b2dc9eac2a1759f45b9ccec55"
PATCHED_SOURCE_SHA = "00d72fdedb2c996e4986497872f2215a9bf1b118c1de4abfe8882e99aa2bbe40"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stage(source, output, patch_program="patch", globals_header=None):
    source, output = source.resolve(strict=True), output.resolve()
    if output.exists() or output.is_relative_to(source) or any((p / ".git").exists() for p in output.parents):
        raise ValueError("Choose a new external output directory outside the native source.")
    parent = json.loads((ROOT / "native/competitive-build.json").read_text())
    before = digest(source / SOURCE)
    if before != parent["dependencies"][SOURCE] or digest(PATCH) != PATCH_SHA:
        raise ValueError("The native controller or shared patch differs from the verified input.")
    with tempfile.TemporaryDirectory(dir=output.parent) as tmp:
        tree = Path(tmp) / "candidate"
        staged = tree / SOURCE
        staged.parent.mkdir(parents=True)
        shutil.copyfile(source / SOURCE, staged)
        subprocess.run([patch_program, "--batch", "--forward", "--binary", "--fuzz=0", "-p1",
                        "--no-backup-if-mismatch", "-i", PATCH.as_posix()], cwd=tree, check=True, timeout=30)
        if digest(staged) != PATCHED_SOURCE_SHA:
            raise ValueError("Patched native source differs from the verified result.")
        result = {"native_source_sha256": before, "shared_patch_sha256": PATCH_SHA,
                  "patched_source_sha256": PATCHED_SOURCE_SHA}
        if globals_header:
            if digest(globals_header) != parent["generated_globals_sha256"]:
                raise ValueError("The generated globals header differs from the native build receipt.")
            for name, expected in parent["dependencies"].items():
                if digest(source / name) != expected:
                    raise ValueError("Native build input differs: " + name)
            includes = Path(tmp) / "generated"
            includes.mkdir()
            shutil.copyfile(globals_header, includes / "globals.h")
            obj = tree / "jkBot.c.o"
            subprocess.run(["cc", *parent["flags"], f"-fmacro-prefix-map={staged}=/src/AI/jkBot.c",
                            "-iquote", source / "src/AI", "-I", source / "src", "-I", includes,
                            "-c", staged, "-o", obj],
                           cwd=tree, check=True, timeout=120)
            result["native_object_sha256"] = digest(obj)
        (tree / "receipt.json").write_text(json.dumps(result, indent=2) + "\n")
        tree.rename(output)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path, help="Assembled native competitive source tree")
    parser.add_argument("--output", required=True, type=Path, help="Fresh directory under an existing external parent")
    parser.add_argument("--patch-program", default="patch", help="GNU patch executable")
    parser.add_argument("--globals-header", type=Path, help="Also compile jkBot.c.o using the pinned Linux inputs")
    args = parser.parse_args()
    print(json.dumps(stage(args.source, args.output, args.patch_program, args.globals_header), indent=2))
