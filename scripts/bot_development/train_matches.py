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
import hashlib
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


def active_pickup(store, scope, map_sha, build_sha):
    """Resolve a qualified native artifact for the next batch; unknown cells play Red."""
    if scope not in ("ffa/guns/noforce", "ffa/guns/force", "tdm/guns/noforce", "tdm/guns/force"):
        return None
    entry = store.active_model("pickup_engage", "|".join((scope, map_sha, build_sha)))
    if not entry:
        return None
    path = store.root / "models" / (entry["sha256"] + ".bin")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
        raise ValueError("Invalid active native pickup weights.")
    from bots.brain import decode_red_native
    decode_red_native(raw)
    return path.resolve()


def rule_scope(args):
    return f"{args.mode}/{args.weapons}/" + ("force" if args.force == "on" else "noforce")


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
        build_flag = "--competitive-build" if args.client_kind == "competitive" else "--transfer-build"
        harness += [build_flag, str(args.client_build),
                    "--mode", args.mode, "--weapons", args.weapons,
                    "--force", args.force,
                    "--episode-file", str(args.episode_file),
                    "--episode-sha256", args.episode_sha256,
                    "--map-sha256", args.map_sha256,
                    "--nav-cache", str(out_dir.parent / f"nav-{index:04d}")]
    if args.brain_edge_model:
        harness += ["--brain-edge-model", str(args.brain_edge_model)]
    if args.model_side:
        side = (("dark", "light")[(index // 2) % 2] if args.model_side == "alternate" else args.model_side)
        harness += ["--model-side", side,
                    "--policy-weights", str(args.policy_weights)]
        if args.client_kind in ("transfer", "competitive"):
            harness += ["--trial-scope", rule_scope(args), "--trial-map-sha256", args.map_sha256,
                        "--trial-weights-sha256", args.weights_digest]
    if args.swap_join_order and index % 2:
        harness += ["--jan-first"]
    harness += args.harness_extra
    inner = "ip link set lo up && exec " + " ".join(
        "'" + part.replace("'", "'\\''") + "'" for part in harness)
    return ["unshare", "-rn", "bash", "-c", inner]


def run_match(args, index: int, suffix: str = "") -> dict:
    out_dir = args.out / f"match-{index:04d}{suffix}"
    if args.client_kind in ("transfer", "competitive"):
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


def evidence_build(binary, controls):
    normal = dict(saber_tracking="both", light_loadout="competitive", force_controller="competitive")
    if not controls or controls == normal:
        return binary
    # Changing either opponent's movement, Force loadout or controller changes
    # the learning environment, even when both executable hashes still match.
    configuration = json.dumps(controls, sort_keys=True, separators=(",", ":")).encode()
    return binary + "@" + hashlib.sha256(configuration).hexdigest()


def ingest_receipt(store, directory: Path, *, split="practice", expected_scope=None, expected_build=None):
    """Import both seats from one verified match under its immutable log identities."""
    from bots.brain import ingest_match_log
    receipt = json.loads((directory / "receipt.json").read_bytes())
    if receipt.get("status") != "live_join_and_loadout_verified":
        raise ValueError("Learning requires a verified native receipt.")
    maps = [digest for key, digest in receipt["sha256"].items() if key.startswith("jkl/")]
    if len(maps) != 1:
        raise ValueError("Expected one verified map.")
    build = receipt["red_policy"]["build"]["binary_sha256"]
    settings = receipt.get("mode_transfer")
    if settings:
        mode, weapons, force = (settings[key] for key in ("mode", "weapons", "force"))
        if force not in ("on", "off"):
            raise ValueError("Invalid Force setting in receipt.")
        scope = f"{mode}/{weapons}/" + ("force" if force == "on" else "noforce")
    else:
        scope = "ffa/guns/force"
    if (expected_scope and scope != expected_scope) or (expected_build and build != expected_build):
        raise ValueError("Requested scope or build does not match the receipt.")
    build = evidence_build(build, receipt.get("competitive_controls"))
    rate = receipt["pace_experiment"]["speed"]
    if rate not in RATES:
        raise ValueError("Invalid pace in receipt.")
    hashes = receipt["log_sha256"]
    if hashlib.sha256((directory / "server.log").read_bytes()).hexdigest() != hashes["server.log"]:
        raise ValueError("Wrong log digest for server.log")
    match_id = hashlib.sha256(":".join(hashes[k] for k in ("server.log", "dark.log", "light.log")).encode()).hexdigest()
    seats = {}
    for name in ("dark.log", "light.log"):
        raw = (directory / name).read_bytes()
        if hashlib.sha256(raw).hexdigest() != hashes[name]:
            raise ValueError("Wrong log digest for " + name)
        seats[name] = raw.decode("utf-8", errors="replace")
    totals = {"match_id": match_id}
    pace = receipt["pace_experiment"]
    for name, raw_text in seats.items():
        start = pace["roles"][Path(name).stem]["first"]["game_ms"]
        game_window = (start, start + 1000 * pace["requested_game_seconds"])
        counts = ingest_match_log(store, raw_text, maps[0], scope, pace=pace_label(rate),
                                  build=build, match_id=match_id, split=split, game_window=game_window)
        for key, value in counts.items():
            totals[key] = totals.get(key, 0) + value
    return totals


def ingest(args, result):
    sys.path.insert(0, str(args.repo))
    from bots.brain import BrainStore
    store = BrainStore(args.brain_root, args.brain_profile)
    try:
        return ingest_receipt(store, Path(result["output"]), split=args.split,
                              expected_scope=args.scope, expected_build=args.build_label)
    finally:
        store.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=REPO)
    parser.add_argument("--data", type=Path, required=True,
                        help="Directory with episode/ and resource/ game data")
    parser.add_argument("--pace-build", type=Path, required=True)
    parser.add_argument("--client-build", type=Path, required=True)
    parser.add_argument("--client-kind", choices=("policy", "transfer", "competitive"), default="policy")
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
    parser.add_argument("--model-side", choices=("dark", "light", "alternate"))
    parser.add_argument("--active-side", choices=("dark", "light", "alternate"),
                        help="Pin the qualified BrainStore artifact for this batch, falling back to Red.")
    parser.add_argument("--swap-join-order", action="store_true",
                        help="Alternate first joiner; with alternate model side, each four runs cross both factors.")
    parser.add_argument("--fit-next", action="store_true",
                        help="Fit and export a candidate from persisted practice evidence after this batch.")
    parser.add_argument("--policy-weights", type=Path)
    parser.add_argument("--mode", choices=("ffa", "tdm", "ctf"), default="ffa")
    parser.add_argument("--weapons", choices=("guns", "sabers"), default="guns")
    parser.add_argument("--force", choices=("on", "off"), default="on")
    parser.add_argument("--episode-file", type=Path)
    parser.add_argument("--episode-sha256")
    parser.add_argument("--map-sha256")
    parser.add_argument("--brain-root", type=Path, help="Ingest ok matches into this BrainStore")
    parser.add_argument("--brain-profile", default="red")
    parser.add_argument("--scope", help="Require the receipt to match this ruleset.")
    parser.add_argument("--split", choices=("practice", "holdout"), default="practice")
    parser.add_argument("--build-label", default="", help="Require this client binary SHA-256 in the receipt")
    parser.add_argument("harness_extra", nargs="*", help="Extra harness args after --")
    args = parser.parse_args()
    if args.harness_extra[:1] == ["--"]:
        args.harness_extra = args.harness_extra[1:]
    if (args.model_side is None) != (args.policy_weights is None):
        parser.error("--model-side and --policy-weights require each other")
    if args.client_kind in ("transfer", "competitive") and not all(
            (args.episode_file, args.episode_sha256, args.map_sha256)):
        parser.error("Transfer and competitive clients require --episode-file/--episode-sha256/--map-sha256")
    if args.client_kind == "policy" and (args.mode, args.weapons, args.force) != ("ffa", "guns", "on"):
        parser.error("Use a transfer build for the selected game rules.")
    if args.active_side and (args.model_side or args.policy_weights):
        parser.error("Choose either the active model or an explicit challenger.")
    if args.fit_next or args.active_side:
        if not args.brain_root or args.client_kind not in ("transfer", "competitive"):
            parser.error("--fit-next and --active-side require a BrainStore and a transfer or competitive client.")
    if args.fit_next and (args.split != "practice" or args.mode == "ctf" or args.weapons != "guns"):
        parser.error("Pickup/fight training needs gun-mode practice games in FFA or TDM.")
    if args.jobs < 0 or args.retries < 0:
        parser.error("--jobs and --retries must be nonnegative")
    if args.matches < 1:
        parser.error("--matches must be positive")
    args.out = args.out.resolve()
    if args.out.exists():
        parser.error(f"output root already exists: {args.out}")
    args.repo, args.data = args.repo.resolve(), args.data.resolve()
    args.pace_build, args.client_build = args.pace_build.resolve(), args.client_build.resolve()
    sys.path.insert(0, str(args.repo))
    if args.episode_file:
        args.episode_file = args.episode_file.resolve(strict=True)
    if args.brain_edge_model:
        args.brain_edge_model = args.brain_edge_model.resolve(strict=True)
    if args.active_side or args.fit_next:
        from bots.brain import BrainStore
        binary = args.client_build / "jk-bot-client"
        args.client_digest = hashlib.sha256(binary.read_bytes()).hexdigest()
    if args.active_side:
        store = BrainStore(args.brain_root, args.brain_profile)
        try:
            args.policy_weights = active_pickup(store, rule_scope(args), args.map_sha256, args.client_digest)
            args.model_side = args.active_side if args.policy_weights else None
        finally:
            store.close()
    if args.policy_weights:
        args.policy_weights = args.policy_weights.resolve(strict=True)
        args.weights_digest = hashlib.sha256(args.policy_weights.read_bytes()).hexdigest()
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
    if args.active_side or args.policy_weights:
        summary["policy"] = {"side": args.model_side, "sha256": getattr(args, "weights_digest", None),
                             "controller": "learned" if args.policy_weights else "teacher"}
    if args.fit_next and ok:
        from bots.brain import DUEL_FEATURES, export_red_neural, save_decision_model, train_outcome_from_store
        store = BrainStore(args.brain_root, args.brain_profile)
        try:
            try:
                model = train_outcome_from_store(store, "pickup_engage", DUEL_FEATURES, scope=rule_scope(args),
                    pace=pace_label(args.rate), build=args.client_digest, teacher_fraction=0.5)
            except ValueError as error:
                summary["candidate"] = {"status": "not_fitted", "reason": str(error)}
            else:
                model_sha = save_decision_model(model, args.out / "candidate.json")
                weights_sha = export_red_neural(model, args.out / "candidate.weights")
                summary["candidate"] = {"status": "fitted", "model_sha256": model_sha, "weights_sha256": weights_sha}
        finally:
            store.close()
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({k: summary[k] for k in
                      ("rate", "jobs", "matches", "verified", "wall_seconds",
                       "requested_game_seconds_total", "aggregate_game_per_wall")}, indent=2))
    return 0 if len(ok) == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
