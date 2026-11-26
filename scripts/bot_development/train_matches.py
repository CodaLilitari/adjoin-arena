"""Run many paced native training matches concurrently and summarize throughput.

Each match is one isolated invocation of the legacy native harness
(``legacy/native_force_observation.py``) inside its own loopback-only
network namespace, exactly like a single hand-run match; this runner only
adds concurrency, per-match output directories, an aggregate summary, and
optional BrainStore ingestion of the bot logs under the match's pace lane.

A match needs three engine processes (dedicated host + two bot clients).
At high pace each is roughly one busy core, so the default job count is
``cpu_count // 4``. Linux/WSL only (``unshare`` user+net namespaces).
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
LEGACY = HERE / "legacy"
REPO = HERE.parents[1]
RATES = (0, 1, 2, 4, 8, 16, 32)


def pace_label(rate: int) -> str:
    return "max" if rate == 0 else f"{rate}x"


def match_command(args, index: int, out_dir: Path) -> list[str]:
    harness = [
        sys.executable, str(LEGACY / "native_force_observation.py"),
        "--repo", str(args.repo), "--data", str(args.data),
        "--output", str(out_dir), "--map", args.map,
        "--duration", str(args.duration), "--arena-baseline",
        "--pace-build", str(args.pace_build), "--pace-rate", str(args.rate),
        "--brain-trace",
    ]
    if args.client_kind == "policy":
        harness += ["--red-policy-build", str(args.client_build)]
    else:
        harness += ["--transfer-build", str(args.client_build),
                    "--mode", args.mode, "--weapons", args.weapons,
                    "--force", args.force,
                    "--episode-file", str(args.episode_file),
                    "--episode-sha256", args.episode_sha256,
                    "--map-sha256", args.map_sha256,
                    "--nav-cache", str(out_dir.parent / f"nav-{index:04d}")]
    if args.brain_edge_model:
        harness += ["--brain-edge-model", str(args.brain_edge_model)]
    if args.model_side:
        harness += ["--model-side", args.model_side,
                    "--policy-weights", str(args.policy_weights)]
    harness += args.harness_extra
    inner = "ip link set lo up && exec " + " ".join(
        "'" + part.replace("'", "'\\''") + "'" for part in harness)
    return ["unshare", "-rn", "bash", "-c", inner]


def run_match(args, index: int, suffix: str = "") -> dict:
    out_dir = args.out / f"match-{index:04d}{suffix}"
    if args.client_kind == "transfer":
        # The harness requires an existing private cache root per match.
        (args.out / f"nav-{index:04d}").mkdir(exist_ok=True)
    started = time.monotonic()
    proc = subprocess.run(match_command(args, index, out_dir), cwd=LEGACY,
                          stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    wall = time.monotonic() - started
    receipt_path = out_dir / "receipt.json"
    result = {"index": index, "output": str(out_dir), "returncode": proc.returncode,
              "wall_seconds": round(wall, 2), "status": "missing_receipt"}
    if proc.returncode != 0 and proc.stderr:
        result["stderr_tail"] = proc.stderr.strip()[-2000:]
    if receipt_path.is_file():
        receipt = json.loads(receipt_path.read_text())
        result["status"] = receipt.get("status", "unknown")
        result["elapsed_wall_seconds"] = receipt.get("elapsed_wall_seconds")
        result["map_sha256"] = receipt.get("sha256", {}).get("jkl/" + args.map)
        roles = receipt.get("pace_experiment", {}).get("roles", {})
        if roles:
            result["observed_rates"] = {r: round(v["observed_rate"], 3) for r, v in roles.items()}
            result["measured_game_seconds"] = {r: v["measured_game_s"] for r, v in roles.items()}
        counts = {}
        for side in ("dark", "light"):
            log = out_dir / f"{side}.log"
            if log.is_file():
                text = log.read_text(encoding="utf-8", errors="replace")
                counts[side] = {"duels": text.count("BOT_DUEL"),
                                "decisions": text.count("BOT_DECISION"),
                                "edge_attempts": text.count("BOT_EDGE_ATTEMPT")}
        result["telemetry"] = counts
    return result


def ingest(args, result: dict) -> dict:
    sys.path.insert(0, str(args.repo))
    from bots.brain import BrainStore, ingest_match_log
    store = BrainStore(args.brain_root, args.brain_profile)
    totals: dict = {}
    try:
        for side in ("dark", "light"):
            log = Path(result["output"]) / f"{side}.log"
            counts = ingest_match_log(
                store, log.read_text(encoding="utf-8", errors="replace"),
                result["map_sha256"], args.scope, pace=pace_label(args.rate),
                build=args.build_label)
            for key, value in counts.items():
                if isinstance(value, int):
                    totals[key] = totals.get(key, 0) + value
    finally:
        store.close()
    return totals


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=REPO)
    parser.add_argument("--data", type=Path, required=True,
                        help="Directory with episode/ and resource/ game data")
    parser.add_argument("--pace-build", type=Path, required=True)
    parser.add_argument("--client-build", type=Path, required=True)
    parser.add_argument("--client-kind", choices=("policy", "transfer"), default="policy")
    parser.add_argument("--out", type=Path, required=True, help="Fresh root for match-XXXX dirs")
    parser.add_argument("--matches", type=int, default=8)
    parser.add_argument("--retries", type=int, default=1,
                        help="Sequential re-runs of failed matches (load-shedding)")
    parser.add_argument("--jobs", type=int, default=0,
                        help="Concurrent matches (default cpu_count//4, min 1)")
    parser.add_argument("--rate", type=int, choices=RATES, default=0,
                        help="Pace rate; 0 = uncapped (fastest measured lane)")
    parser.add_argument("--duration", type=int, default=120, help="Requested game seconds")
    parser.add_argument("--map", default="m10.jkl")
    parser.add_argument("--brain-edge-model", type=Path)
    parser.add_argument("--model-side", choices=("dark", "light"))
    parser.add_argument("--policy-weights", type=Path)
    parser.add_argument("--mode", choices=("ffa", "tdm", "ctf"), default="ffa")
    parser.add_argument("--weapons", choices=("guns", "sabers"), default="guns")
    parser.add_argument("--force", choices=("on", "off"), default="on")
    parser.add_argument("--episode-file", type=Path)
    parser.add_argument("--episode-sha256")
    parser.add_argument("--map-sha256")
    parser.add_argument("--brain-root", type=Path, help="Ingest ok matches into this BrainStore")
    parser.add_argument("--brain-profile", default="red")
    parser.add_argument("--scope", default="ffa/guns/force")
    parser.add_argument("--build-label", default="", help="BrainStore build tag for ingested rows")
    parser.add_argument("harness_extra", nargs="*", help="Extra harness args after --")
    args = parser.parse_args()
    if args.harness_extra[:1] == ["--"]:
        args.harness_extra = args.harness_extra[1:]
    if (args.model_side is None) != (args.policy_weights is None):
        parser.error("--model-side and --policy-weights require each other")
    if args.client_kind == "transfer" and not all(
            (args.episode_file, args.episode_sha256, args.map_sha256)):
        parser.error("--client-kind transfer requires --episode-file/--episode-sha256/--map-sha256")
    if args.matches < 1:
        parser.error("--matches must be positive")
    args.out = args.out.resolve()
    if args.out.exists():
        parser.error(f"output root already exists: {args.out}")
    args.repo, args.data = args.repo.resolve(), args.data.resolve()
    args.pace_build, args.client_build = args.pace_build.resolve(), args.client_build.resolve()
    jobs = args.jobs or max(1, (os.cpu_count() or 4) // 4)
    args.out.mkdir(parents=True)

    started = time.monotonic()
    results = []
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        futures = {pool.submit(run_match, args, i): i for i in range(args.matches)}
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            print(f"[{result['index']:04d}] {result['status']} wall={result['wall_seconds']}s", flush=True)
    # Oversubscription can fail pace verification under load; retry those
    # matches one at a time so a loaded machine loses evidence loudly in
    # the summary, not silently.
    for attempt in range(1, args.retries + 1):
        failed = [r for r in results if r["status"] != "live_join_and_loadout_verified"]
        if not failed:
            break
        for old in failed:
            result = run_match(args, old["index"], suffix=f"-retry{attempt}")
            prior = {k: v for k, v in old.items() if k != "attempts"}
            result["attempts"] = [*old.get("attempts", []), prior]
            results[results.index(old)] = result
            print(f"[{result['index']:04d}] retry{attempt} {result['status']} "
                  f"wall={result['wall_seconds']}s", flush=True)
    if args.brain_root:
        for result in results:
            if result["status"] == "live_join_and_loadout_verified":
                result["ingested"] = ingest(args, result)
    wall = time.monotonic() - started
    results.sort(key=lambda r: r["index"])
    ok = [r for r in results if r["status"] == "live_join_and_loadout_verified"]
    game_seconds = sum(args.duration for _ in ok)
    summary = {
        "schema": 1, "rate": args.rate, "pace_label": pace_label(args.rate),
        "duration_game_seconds": args.duration, "map": args.map, "jobs": jobs,
        "matches": len(results), "verified": len(ok),
        "wall_seconds": round(wall, 2),
        "requested_game_seconds_total": game_seconds,
        "aggregate_game_per_wall": round(game_seconds / wall, 3) if wall else None,
        "results": results,
    }
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({k: summary[k] for k in
                      ("rate", "jobs", "matches", "verified", "wall_seconds",
                       "requested_game_seconds_total", "aggregate_game_per_wall")}, indent=2))
    return 0 if len(ok) == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
