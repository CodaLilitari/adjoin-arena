"""Stage the four navigation-candidate engine sources from a packaged source tree."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[2]
BASE_FILES = ("src/AI/jkBot.c", "src/AI/jkBotNavigate.inc", "src/AI/jkBotNavigation.inc")
HINT = "src/AI/jkBotRouteHints.inc"
NAV = "competitive-navigation.patch"
RAMP = "supported-ramp.patch"
STEPS = (("reverse", RAMP), ("reverse", NAV), ("apply", "candidate/" + NAV),
         ("apply", "candidate/" + RAMP), ("apply", "candidate/competitive-route-hints.patch"))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def packaged(target):
    folder = ROOT / target
    manifest = folder / ("competitive-build.json" if target == "native" else "BUILD.json")
    record = json.loads(manifest.read_text())
    if target == "native":
        inputs = {folder / name: digest for name, digest in record["competitive_overlays"].items()}
        inputs[folder / "build_competitive.py"] = record["competitive_builder_sha256"]
        stock = json.loads((folder / "competitive-stock-build.json").read_text())
        inputs[manifest] = stock["competitive_receipt_sha256"]
        inputs[folder / "build_competitive_stock.py"] = stock["builder_sha256"]
        sources = record["dependencies"]
    else:
        inputs = {ROOT / name: record["files"][name]["sha256"] for name in record["patches"]}
        sources = record["changed_sources"]
    for path, digest in inputs.items():
        if sha(path) != digest:
            raise ValueError(f"Packaged build input differs from its receipt: {path.name}")
    return manifest, {name: sources[name] for name in BASE_FILES}


def stage(target, source, output, patch_program="patch", *, jhs_landing=False, jhs_landing_step=False):
    source, output = source.resolve(strict=True), output.resolve()
    if (output.exists() or output.is_relative_to(source) or not output.parent.is_dir() or
            any((parent / ".git").exists() for parent in (output, *output.parents))):
        raise ValueError("Choose a fresh output outside the source tree and checkouts, under an existing directory.")
    manifest, expected = packaged(target)
    if (source / HINT).exists() or any(sha(source / name) != digest for name, digest in expected.items()):
        raise ValueError("The input source must match the assembled packaged engine.")
    with tempfile.TemporaryDirectory(prefix="navigation-stage-", dir=output.parent) as tmp:
        tree = Path(tmp) / "candidate"
        (tree / "src/AI").mkdir(parents=True)
        for name in BASE_FILES:
            shutil.copyfile(source / name, tree / name)
        steps = []
        operations = STEPS
        if jhs_landing or jhs_landing_step:
            operations += (("apply", "candidate/jhs-landing.patch"),)
        if jhs_landing_step:
            operations += (("apply", "candidate/jhs-landing-step.patch"),)
        for direction, name in operations:
            overlay = ROOT / target / name
            subprocess.run([patch_program, "--batch", "--binary", "--fuzz=0", "--no-backup-if-mismatch",
                            "--reverse" if direction == "reverse" else "--forward", "-p1", "-i",
                            overlay.as_posix()], cwd=tree, check=True, timeout=20, stdout=subprocess.DEVNULL)
            steps.append({"operation": direction, "path": f"{target}/{name}", "sha256": sha(overlay)})
        files = {name: sha(tree / name) for name in (*BASE_FILES, HINT)}
        record = {"target": target, "packaged_manifest_sha256": sha(manifest), "input_files": expected,
                  "steps": steps, "output_files": files}
        (tree / "manifest.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        tree.rename(output)
    return record


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=("native", "web_bots"), required=True)
    parser.add_argument("--source", required=True, type=Path, help="Assembled packaged engine source")
    parser.add_argument("--out", required=True, type=Path, help="Fresh external output directory")
    parser.add_argument("--patch-program", default="patch", help="GNU patch executable")
    parser.add_argument("--jhs-landing", action="store_true", help="Include the verified JHS final bridge landing")
    parser.add_argument("--jhs-landing-step", action="store_true", help="Include full-radius near-field landing clearance")
    args = parser.parse_args()
    stage(args.target, args.source, args.out, args.patch_program,
          jhs_landing=args.jhs_landing, jhs_landing_step=args.jhs_landing_step)
    print(args.out / "manifest.json")
