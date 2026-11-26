"""Schedule or run legal, digest-pinned JK multiplayer map and ruleset trials on Linux."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
JHS_GOB = "a62c94789c521af2746cc8378301a4940a59a24f6fb44dd4c443caacc0211b04"
JHS_MAP = "90e2641a58e0ec0102355dca9d3ec5eb55c4cbc9945a427227dcc8244885619d"


def schedule(root=ROOT):
    audit = json.loads((root / "qa/bots-stock-map-audit.json").read_bytes())
    episodes = [*audit["episodes"], {"episode": "jhs", "archive_sha256": JHS_GOB,
                "maps": [{"map": "jhs.jkl", "sha256": JHS_MAP}]}]
    rows = []
    for episode in episodes:
        name = episode["episode"]
        modes = ("ctf",) if name == "jk1ctf" else ("ffa", "tdm")
        for level in episode["maps"]:
            for mode in modes:
                for weapons in ("guns", "sabers"):
                    for force in ("off", "on"):
                        key = "-".join((Path(level["map"]).stem, mode, weapons, force))
                        rows.append(dict(key=key, episode=name, episode_sha256=episode["archive_sha256"],
                                         map=level["map"], map_sha256=level["sha256"], mode=mode,
                                         weapons=weapons, force=force))
    return rows


def run_cell(args, cell):
    directory = args.output / cell["key"]
    directory.mkdir(exist_ok=False)
    nav = directory / "cache"
    nav.mkdir()
    jhs = cell["episode"] == "jhs"
    archive = args.jhs_gob if jhs else args.data / "episode" / (cell["episode"] + ".gob")
    command = ["unshare", "-Urn", "--", "sh", "-c", 'ip link set lo up && exec "$@"', "sh",
               sys.executable, "-B", str(args.repo / "scripts/bot_development/legacy/native_force_observation.py"),
               "--repo", str(args.repo), "--arena-baseline", "--data", str(args.data),
               "--pace-build", str(args.pace_build), "--pace-rate", str(args.rate),
               "--duration", str(args.seconds), "--mode", cell["mode"], "--weapons", cell["weapons"],
               "--force", cell["force"], "--episode-file", str(archive), "--map", cell["map"],
               "--episode-sha256", cell["episode_sha256"], "--map-sha256", cell["map_sha256"],
               "--nav-cache", str(nav), "--output", str(directory / "match")]
    if args.brain_trace:
        command.append("--brain-trace")
    if jhs and args.jhs_client == "hints":
        route = args.repo / "bots/routes/jhs-school-entry.route"
        scope = "/".join((cell["mode"], cell["weapons"], "force" if cell["force"] == "on" else "noforce"))
        command += ["--hint-build", str(args.hint_build), "--route-hint", str(route),
                    "--route-hint-sha256", hashlib.sha256(route.read_bytes()).hexdigest(),
                    "--route-hint-scope", scope]
    elif jhs and args.jhs_client == "platform":
        command += ["--platform-build", str(args.platform_build)]
    else:
        command += ["--competitive-build", str(args.stock_build)]
    if args.jan_first:
        command.append("--jan-first")
    (directory / "command.json").write_text(json.dumps(command, indent=2) + "\n")
    with (directory / "driver.log").open("wb") as log:
        result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT,
                                env=dict(os.environ, OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1"))
    receipt = directory / "match/receipt.json"
    record = json.loads(receipt.read_bytes()) if receipt.is_file() else {}
    print(cell["key"], result.returncode, record.get("status"), record.get("failure", ""), flush=True)
    return result.returncode == 0 and record.get("status") == "live_join_and_loadout_verified"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=ROOT)
    parser.add_argument("--run", action="store_true", help="Default prints the schedule as JSON.")
    parser.add_argument("--episode", action="append", choices=("jk1mp", "jk1ctf", "jhs"))
    parser.add_argument("--cell", action="append", help="Select an exact schedule key; repeatable.")
    parser.add_argument("--output", type=Path, help="External directory. Each selected cell must be fresh.")
    parser.add_argument("--seconds", type=int, default=30)
    parser.add_argument("--rate", type=int, choices=(1, 2, 4), default=2)
    parser.add_argument("--jan-first", action="store_true")
    parser.add_argument("--brain-trace", action="store_true", help="Extended telemetry on builds that support it.")
    parser.add_argument("--jhs-client", choices=("hints", "platform", "competitive"), default="hints",
                        help="JHS native build with entrance hints, platform support, or integrated competitive control.")
    for key in ("data", "pace-build", "stock-build", "jhs-gob", "hint-build", "platform-build"):
        parser.add_argument("--" + key, type=Path)
    args = parser.parse_args()
    cells = [cell for cell in schedule(args.repo)
             if (not args.episode or cell["episode"] in args.episode)
             and (not args.cell or cell["key"] in args.cell)]
    if not cells or set(args.cell or ()) - {cell["key"] for cell in cells}:
        parser.error("No matching cell or unrecognized cell key")
    if not args.run:
        print(json.dumps(cells, indent=2))
        return
    if not (args.output and args.data and args.pace_build and args.seconds >= 15):
        parser.error("Runs require an external --output, --data, --pace-build and at least 15 seconds")
    if any(c["episode"] == "jhs" for c in cells):
        if not args.jhs_gob:
            parser.error("JHS requires --jhs-gob")
        if args.jhs_client == "hints" and not args.hint_build:
            parser.error("The hints client requires --hint-build")
        if args.jhs_client == "platform" and not args.platform_build:
            parser.error("The platform client requires --platform-build")
    if any(c["episode"] != "jhs" or args.jhs_client == "competitive" for c in cells) and not args.stock_build:
        parser.error("Competitive-client cells require --stock-build")
    if args.output.resolve().is_relative_to(args.repo.resolve()):
        parser.error("Keep match output outside the checkout")
    args.output.mkdir(exist_ok=True, parents=True)
    if any((args.output / c["key"]).exists() for c in cells):
        parser.error("Selected cell output already exists; use a new directory for repeat runs")
    success = True
    for cell in cells:
        success = run_cell(args, cell) and success
    raise SystemExit(0 if success else 1)


if __name__ == "__main__":
    main()
