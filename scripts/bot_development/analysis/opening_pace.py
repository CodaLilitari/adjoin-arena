"""Compare matched opening behavior and the observed game-to-wall pace of three native processes."""
import argparse
from collections import Counter
from itertools import groupby
import json
from pathlib import Path
import re
from statistics import median

from .native_duel import require, sha
from .opening_detour import PICKUPS, PLAN
from .planner_start import EXPECTED, FIRST_PROFILE
from .start_crossover import read_match


ROOT = Path(__file__).resolve().parents[3]
SCHEDULE = ROOT / "qa/adjoin-arena-opening-pace-schedule.json"
PRIOR = ROOT / "qa/adjoin-arena-planner-start.json"
HUD_WEAPON = {hud: weapon for weapon, hud in PICKUPS.values()}


def opening_path(path, seat):
    """Stop at the first monitored HUD pickup in the opening life, even if the initial policy choice changed."""
    plans = []
    began = released = False
    hud = None
    with path.open("rb") as src:
        for line_number, raw in enumerate(src, 1):
            line = raw.strip().decode("ascii", errors="replace")
            if not began:
                began = line == "ADJOIN_OPENING"
                continue
            if line in ("ADJOIN_OPENING", "ADJOIN_RESPAWN") or line.startswith(("BOT_RESPAWN ", "OpenJKDF2: sithWorld_Load -> ")):
                break
            if line == "GATE_UNLOCK_APPLIED":
                released = True
            elif line.startswith("BOT_GEAR ") and "event=plan" in line.split():
                m = PLAN.fullmatch(line)
                require(m and m[1] == seat["name"] and released, "Unexpected gear record or pre-release plan")
                plans.append({"item": int(m[3]), "pack": m[4] == "1", "direct": m[5] == "1", "line": line_number})
            elif line in HUD_WEAPON:
                require(released, "Monitored weapon pickup message before release")
                hud = {"weapon": HUD_WEAPON[line], "line": line_number}
                break
    require(began and released, "Missing opening life or unlock")
    target = plans[0]["item"] if plans else None
    if plans:
        require(target == seat["first_plan_item"], "First opening plan disagrees with the qualified owner log")
    gains = {k: x for k, x in seat["first_life_gain_seconds_after_release"].items() if x is not None}
    earliest = min(gains.values(), default=None)
    first_weapons = sorted(k for k, x in gains.items() if x == earliest)
    matches = hud is not None and first_weapons == [hud["weapon"]]
    expected_item, expected_weapon = EXPECTED[seat["sector"]]
    if not plans:
        reason = "no_plan_before_pickup" if hud else "missing_opening_plan"
    elif not hud:
        reason = "no_monitored_pickup_message"
    elif not first_weapons:
        reason = "no_monitored_inventory_gain"
    elif len(first_weapons) > 1:
        reason = "simultaneous_sampled_weapon_gains"
    elif not matches:
        reason = "first_hud_and_inventory_weapon_disagree"
    else:
        reason = None
    sequence = [item for item, _ in groupby(p["item"] for p in plans)]
    return {"player": seat["name"], "slot": seat["slot"], "sector": seat["sector"],
            "expected_item": expected_item, "expected_weapon": expected_weapon,
            "first_target": target, "first_plan_direct": plans[0]["direct"] if plans else None,
            "initial_target_correct": target == expected_item and not plans[0]["pack"],
            "plans": plans, "target_sequence": sequence,
            "path_endpoint": "first_monitored_pickup_hud" if hud else "opening_life_end_or_cutoff",
            "pickup_hud": hud, "sampled_first_weapons": first_weapons, "owner_first_life_gain_s": gains,
            "qualified_weapon": hud["weapon"] if reason is None else None,
            "qualified_gain_s": earliest if reason is None else None, "unresolved_reason": reason}


def paired_owner(normal, fast, fine, band):
    for field in ("player", "slot", "sector", "expected_item", "expected_weapon"):
        require(normal[field] == fast[field], "Paired owner identity or opening changed")
    both_targets = normal["first_target"] is not None and fast["first_target"] is not None
    both_pickups = normal["qualified_weapon"] is not None and fast["qualified_weapon"] is not None
    same_weapon = both_pickups and normal["qualified_weapon"] == fast["qualified_weapon"]
    # A different or missing intended weapon remains an outcome, without a timing vote.
    same_weapon_delta = (round(fast["qualified_gain_s"] - normal["qualified_gain_s"], 6)
                         if same_weapon else None)
    timing = (same_weapon and normal["qualified_weapon"] == normal["expected_weapon"]
              and normal["initial_target_correct"] and fast["initial_target_correct"])
    delta = same_weapon_delta if timing else None
    return {"player": normal["player"], "slot": normal["slot"], "sector": normal["sector"],
            "first_targets": [normal["first_target"], fast["first_target"]],
            "same_initial_target": normal["first_target"] == fast["first_target"] if both_targets else None,
            "target_sequences": [normal["target_sequence"], fast["target_sequence"]],
            "same_target_sequence": normal["target_sequence"] == fast["target_sequence"] if both_pickups else None,
            "same_corroborated_weapon": same_weapon if both_pickups else None,
            "weapons": [normal["qualified_weapon"], fast["qualified_weapon"]],
            "owner_gain_game_s": [normal["qualified_gain_s"], fast["qualified_gain_s"]],
            "same_observed_weapon_delta_game_s": same_weapon_delta, "fast_minus_normal_game_s": delta, "exact_time": delta == 0 if timing else None,
            "same_rounded_elapsed_millisecond": (round(normal["qualified_gain_s"] * 1000) ==
                                                 round(fast["qualified_gain_s"] * 1000)) if timing else None,
            "within_secondary_band": abs(delta) <= fine if timing else None,
            "within_agreement_band": abs(delta) <= band if timing else None,
            "unresolved": [normal["unresolved_reason"], fast["unresolved_reason"]]}


def summarize(owners):
    deltas = [x["fast_minus_normal_game_s"] for x in owners if x["fast_minus_normal_game_s"] is not None]
    def count(key):
        return {"agree": sum(x[key] is True for x in owners), "differ": sum(x[key] is False for x in owners),
                "unresolved": sum(x[key] is None for x in owners)}
    return {"paired_openings": len(owners), "same_initial_target": count("same_initial_target"),
            "same_target_sequence": count("same_target_sequence"), "same_corroborated_weapon": count("same_corroborated_weapon"),
            "exact_time": count("exact_time"),
            "same_rounded_elapsed_millisecond": count("same_rounded_elapsed_millisecond"),
            "within_secondary_band": count("within_secondary_band"), "within_agreement_band": count("within_agreement_band"),
            "median_signed_delta_game_s": median(deltas) if deltas else None,
            "max_absolute_delta_game_s": max(map(abs, deltas), default=None)}


def check_schedule(cells):
    require(len(cells) == 16 and [r["index"] for r in cells] == list(range(1, 17)), "Expected sixteen scheduled runs")
    counts = Counter()
    for start in range(0, 16, 2):
        a, b = cells[start:start+2]
        require(a["pair"] == b["pair"] == 1 + start // 2 and a["first"] == b["first"] and a["starts"] == b["starts"]
                and {a["speed"], b["speed"]} == {1, 2}, "Mismatched paired runs in frozen schedule")
        counts[a["first"], a["starts"], a["speed"]] += 1
    require(counts == Counter({(first, layout, speed): 1 for first in FIRST_PROFILE
                               for layout in ("normal", "swapped") for speed in (1, 2)}), "Unbalanced pace schedule")


CLOCK = re.compile(r"ARENA_PACE role=(host|dark|light) pid=(\d+) rate=(\d+) frame=(\d+) "
                   r"game_ms=(\d+) mono_ns=(\d+) step_ms=(\d+) applied_ms=(\d+)")
CLOCK_FIELDS = ("role", "pid", "rate", "frame", "game_ms", "mono_ns", "step_ms", "applied_ms")
ROLE_LOGS = {"host": "server.log", "dark": "dark.log", "light": "light.log"}


def read_native_samples(path, role):
    rows = []
    gates = []
    world_line = None
    for line_number, line in enumerate(path.read_text(encoding="ascii", errors="replace").splitlines()):
        text = line.strip()
        if text == "OpenJKDF2: sithWorld_Load -> m10.jkl":
            world_line = line_number
        if text == ("GATE_HOST_ACK" if role == "host" else "GATE_UNLOCK_APPLIED"):
            gates.append(line_number)
        if text.startswith("ARENA_PACE"):
            match = CLOCK.fullmatch(text)
            require(match and match[1] == role, "Malformed or misplaced native clock marker")
            row = dict(zip(CLOCK_FIELDS, (match[1], *map(int, match.groups()[1:])), strict=True))
            rows.append((line_number, row))
    require(len(gates) == (2 if role == "host" else 1), "Missing native release or host acknowledgements")
    require(world_line is not None, "Missing Canyon Oasis clock epoch")
    return [pair for pair in rows if pair[0] >= world_line], gates[-1]


def measure_rate(rows, first, last, speed):
    require(all(r["applied_ms"] == r["step_ms"] == 34 for r in rows), "Native applied step differs from 34 ms")
    require(len(rows) >= 3 and rows[0] == first and rows[-1] == last, "Missing paced interval")
    game_intervals = []
    wall_intervals = []
    frame_intervals = []
    for a, b in zip(rows, rows[1:]):
        dt = b["mono_ns"] - a["mono_ns"]
        game_dt = b["game_ms"] - a["game_ms"]
        frames = b["frame"] - a["frame"]
        require(dt > 0 and frames == 5 and game_dt == 5 * first["step_ms"],
                "Missing native sample, clock discontinuity, or inconsistent applied step")
        game_intervals.append(game_dt)
        wall_intervals.append(dt / 1e6)
        frame_intervals.append(frames)
    game_s = (last["game_ms"] - first["game_ms"]) / 1000
    wall_s = (last["mono_ns"] - first["mono_ns"]) / 1e9
    slope = game_s / wall_s
    require(22 <= game_s <= 22.65 and first["game_ms"] + 22000 > rows[-2]["game_ms"],
            "Interval did not stop at the first sample reaching 22 game seconds")
    require(0.9 * speed <= slope <= 1.1 * speed, "Measured native game/wall rate outside the validity band")
    return {"observed_rate": round(slope, 6), "game_seconds": round(game_s, 6), "wall_seconds": round(wall_s, 6),
            "samples": len(rows), "first": first, "last": last,
            "marker_wall_ms_min_median_max": [round(f(wall_intervals), 6) for f in (min, median, max)],
            "marker_game_ms_min_median_max": [f(game_intervals) for f in (min, median, max)],
            "nonfive_frame_gaps": sum(n != 5 for n in frame_intervals),
            "non_nominal_game_intervals": sum(dt != n * first["step_ms"] for dt, n in zip(game_intervals, frame_intervals))}


def read_clocks(directory, pace, gate, paths):
    path = directory / "pace-trace.jsonl"
    require(sha(path) == pace["trace_sha256"], "Clock trace hash mismatch")
    speed, start, end = pace["speed"], pace["start_monotonic_ns"], pace["end_monotonic_ns"]
    require(speed in (1, 2) and pace["requested_game_seconds"] == 22 and 0 < start < end,
            "Invalid pace or common wall-time interval")
    trace = {role: [] for role in ROLE_LOGS}
    for line in path.read_bytes().splitlines():
        row = json.loads(line)
        require(isinstance(row, dict) and set(row) == set(CLOCK_FIELDS) and
                all(type(row[k]) is int for k in CLOCK_FIELDS[1:]) and row["role"] in trace,
                "Unknown clock trace schema")
        trace[row["role"]].append(row)
    require(set(pace["roles"]) == set(ROLE_LOGS), "Unexpected native clock roles")
    result = {}
    for role, name in ROLE_LOGS.items():
        raw, release_line = read_native_samples(directory / name, role)
        entry = pace["roles"][role]
        pid = entry["pid"]
        require(raw and pid > 0 and all(r["pid"] == pid and r["rate"] == speed and r["step_ms"] == 34
                                        for _, r in raw), "Clock trace belongs to another process, speed or step")
        in_window = [(line, row) for line, row in raw if start <= row["mono_ns"] <= end]
        require(all(line > release_line for line, _ in in_window), "Shared clock interval overlaps the hold")
        eligible = [row for _, row in in_window]
        require(eligible and eligible[0] == entry["first"], "Incorrect common-clock starting sample")
        first = eligible[0]
        target = first["game_ms"] + 22000
        last_i = next((i for i, r in enumerate(eligible) if r["game_ms"] >= target), None)
        require(last_i is not None and eligible[last_i] == entry["last"], "Incorrect common-clock cutoff sample")
        span = eligible[:last_i+1]
        # All native samples inside the measured interval must be independently present in
        # the launcher trace, even if the trace also retains discovery or shutdown samples.
        traced = [r for r in trace[role] if first["mono_ns"] <= r["mono_ns"] <= span[-1]["mono_ns"]]
        require(span == traced, "Per-process raw log and collected clock trace disagree")
        clock = measure_rate(span, first, span[-1], speed)
        final = entry["final_sample"]
        require(final in eligible and final["mono_ns"] >= span[-1]["mono_ns"],
                "Last observed native sample not in qualified window")
        tail = round((eligible[-1]["game_ms"] - first["game_ms"] - 22000) / 1000, 6)
        require(0 <= tail <= .65, "Raw native log ran beyond the permitted shared-game window")
        collected_tail = (final["game_ms"] - first["game_ms"] - 22000) / 1000
        require(abs(clock["game_seconds"] - entry["measured_game_s"]) <= .000001
                and abs(clock["wall_seconds"] - entry["measured_wall_s"]) <= .000001
                and abs(collected_tail - entry["observed_game_tail_s"]) <= .000001,
                "Reported duration or tail disagrees with native clocks")
        clock["observed_tail_game_s"] = tail
        require(abs(clock["observed_rate"] - entry["observed_rate"]) <= .001, "Recorded rate disagrees with clock samples")
        release_s = (gate["host_acknowledgements"][-1]["host_time_s"] if role == "host"
                     else gate["owners"][role]["unlock_time_s"])
        require(first["game_ms"] >= round(release_s * 1000), "Clock interval begins before release")
        clock.update(pid=pid, first_sample_lag_wall_s=round((first["mono_ns"]-start)/1e9, 6),
                     cutoff_after_last_sample_wall_s=round((end-span[-1]["mono_ns"])/1e9, 6))
        if role != "host":
            clock["opening_rate"] = opening_rate(raw, release_line, gate["owners"][role]["release_time_s"],
                                                 paths[role]["qualified_gain_s"])
        result[role] = clock
    require(len({c["pid"] for c in result.values()}) == 3, "Native process identities overlap")
    return result


def opening_rate(raw, release_line, release_s, gain_after_release):
    """Bracket the COG-measured event with real host-clock samples; keep endpoint precision independent."""
    if gain_after_release is None:
        return {"status": "unavailable", "reason": "no_corroborated_pickup"}
    start = round(release_s * 1000)
    stop = round((release_s + gain_after_release) * 1000)
    ends = [r for line, r in raw if line >= release_line and r["game_ms"] >= stop]
    preceding = [r for line, r in raw if line < release_line and r["game_ms"] <= start]
    following = [r for line, r in raw if line >= release_line and r["game_ms"] >= start]
    if not ends or not (preceding or following):
        return {"status": "unavailable", "reason": "no_clock_bracket"}
    first = preceding[-1] if preceding else following[0]
    last = ends[0]
    interval = [r for _, r in raw if first["mono_ns"] <= r["mono_ns"] <= last["mono_ns"]]
    if len(interval) < 2 or first["game_ms"] >= stop or last["mono_ns"] <= first["mono_ns"]:
        return {"status": "unavailable", "reason": "pickup_interval_shorter_than_available_samples"}
    require(all(r["rate"] == first["rate"] and r["pid"] == first["pid"] for r in interval)
            and all(b["mono_ns"] > a["mono_ns"] and b["game_ms"] >= a["game_ms"]
                    for a, b in zip(interval, interval[1:])), "Invalid opening-clock segment")
    game_ms = last["game_ms"] - first["game_ms"]
    wall_s = (last["mono_ns"] - first["mono_ns"]) / 1e9
    return {"status": "bracketed" if preceding else "partial_from_first_sample_after_release",
            "observed_rate": round(game_ms / 1000 / wall_s, 6),
            "samples": len(interval), "wall_seconds": round(wall_s, 6), "game_ms": game_ms,
            "first_sample_minus_release_game_ms": first["game_ms"] - start,
            "last_sample_minus_pickup_game_ms": last["game_ms"] - stop,
            "non_nominal_applied_samples": sum(r["applied_ms"] != r["step_ms"] for r in interval)}


def read_run(directory, cell, prior, build):
    receipt = json.loads((directory / "receipt.json").read_bytes())
    pace = receipt["pace_experiment"]
    require(pace["build"] == build and build["step_ms"] == 34 and build["rates"] == [1, 2]
            and pace["speed"] == cell["speed"] and pace["trace"] == "pace-trace.jsonl",
            "Incorrect native pace build or scheduled arm")
    match, fixture, config = read_match(directory, allow_no_plan=True, expected_pacing="native pace experiment",
                                        expected_host_sha=build["host"]["binary_sha256"])
    planner = receipt["planner_experiment"]
    require(match["assignment"] == cell["starts"] and config["seat_order"][0] == FIRST_PROFILE[cell["first"]]
            and planner["mode"] == "on" and planner["build"] == build["bot"], "Incorrect opening, seat order, or planner")
    require(fixture == prior["fixtures"][cell["starts"]], "Episode or level differs from the original planner-on fixture")
    config.pop("seat_order")
    config["initial_force_stars"] = {s: b["first_stars"] for s, b in receipt["bots"].items()}
    previous = prior["configuration"]
    for key in ("bot_options", "seed_control", "requested_match_seconds", "server_registry", "profiles",
                "render_environment", "initial_force_stars"):
        require(config[key] == previous[key], "Changed prior scenario setting: " + key)
    for name in ("bots/profiles.json", "bots/run.py", "bots/companion.py", "bots/settings.py", "manager/config.py",
                 "manager/content.py", "web_gateway/ipc.py", "manager/spectator.py", "manager/spectator_geometry.py"):
        require(config["launcher_input_sha256"][name] == previous["launcher_input_sha256"][name],
                "Pinned game or camera source changed: " + name)
    baseline_hashes = previous["binary_and_map_hashes"]
    for name in ("jkl/m10.jkl", "res1hi.gob", "res2.gob"):
        require(config["binary_and_map_hashes"][name] == baseline_hashes[name], "Pinned game resource changed: " + name)
    original_planner = previous["research_build"]
    require(build["bot"]["base_binary_sha256"] == original_planner["binary_sha256"]
            and build["bot"]["planner_object_sha256"] == original_planner["rebuilt_object_sha256"]
            and build["host"]["base_binary_sha256"] == previous["observed_process_images"]["server"]["executable_sha256"],
            "Paced images are not derived from the qualified planner and host")
    images = pace["loaded_images"]
    require(set(images) == set(ROLE_LOGS), "Expected three measured native images")
    for role in ROLE_LOGS:
        pin = build["host" if role == "host" else "bot"]
        expected = {"executable_sha256": pin["binary_sha256"], "networking_library_sha256": pin["gns_sha256"]}
        require(planner["loaded_images"]["server" if role == "host" else role] == expected
                and images[role] == dict(**expected, pid=pace["roles"][role]["pid"]),
                "Native executable, loaded library or clock process identity differs")
    gate = receipt["ready_gate_observations"]
    paths = {}
    for side, seat in match["seats"].items():
        require(seat["slot"] == gate["owners"][side]["slot"] and planner["owners"][side] == gate["owners"][side]["planner"]
                and planner["owners"][side]["mode"] == "on" and not seat["first_plan_during_hold"],
                "Unqualified start-on-release planner")
        args = receipt["bots"][side]["argv"]
        require(args[args.index("-botConnect")+1] == f"127.0.0.1:{receipt['server_registry']['portNum']}",
                "Owner did not target the measured private host")
        paths[side] = opening_path(directory / (side + ".log"), seat)
    clocks = read_clocks(directory, pace, gate, paths)
    launcher_seconds = receipt["elapsed_wall_seconds"]
    shared_seconds = match["shared_observation_wall_seconds"]
    require(0 < shared_seconds <= launcher_seconds, "Invalid elapsed match or launcher wall time")
    return dict(**cell, source_receipt_sha256=match["source_receipt_sha256"], log_sha256=match["logs_sha256"],
                pace_trace_sha256=pace["trace_sha256"], owners=paths, clocks=clocks, video=match["video"],
                shared_wall_seconds=shared_seconds, launcher_elapsed_wall_s=launcher_seconds), config


def evaluate(directories, schedule_path=SCHEDULE):
    schedule = json.loads(schedule_path.read_bytes())
    cells = schedule["runs"]
    check_schedule(cells)
    require(len(directories) == len(cells) and schedule["planner"] == "on" and schedule["speeds"] == [1, 2],
            "Supply the sixteen planner-on matches in frozen schedule order")
    fine, band = schedule["secondary_band_game_s"], schedule["agreement_band_game_s"]
    require((fine, band) == (.10, .20), "Unexpected registered agreement bands")
    prior = json.loads(PRIOR.read_bytes())
    build_path = ROOT / "native/pace-build.json"
    build = json.loads(build_path.read_bytes())
    common = None
    runs, pairs = [], []
    for directory, cell in zip(directories, cells, strict=True):
        row, config = read_run(directory, cell, prior, build)
        if common is None:
            common = config
        require(config == common, "Matched build, inputs or configuration changed within paced series")
        runs.append(row)
    require(len({r["log_sha256"]["server.log"] for r in runs}) == len(runs)
            and len({r["pace_trace_sha256"] for r in runs}) == len(runs), "Reused match or clock trace")
    for _, grouped in groupby(runs, key=lambda r: r["pair"]):
        normal, fast = sorted(grouped, key=lambda r: r["speed"])
        owners = [paired_owner(normal["owners"][s], fast["owners"][s], fine, band) for s in ("dark", "light")]
        pairs.append(dict(pair=normal["pair"], first=normal["first"], starts=normal["starts"],
                          normal_index=normal["index"], fast_index=fast["index"], owners=owners))
    owners = [o for pair in pairs for o in pair["owners"]]
    summaries = {"all": summarize(owners),
                 "by_slot": {str(s): summarize([o for o in owners if o["slot"] == s]) for s in (1, 2)},
                 "by_player": {n: summarize([o for o in owners if o["player"] == n]) for n in sorted({o["player"] for o in owners})}}
    rate_summary = {}
    for speed in (1, 2):
        arm = [r for r in runs if r["speed"] == speed]
        rate_summary[str(speed)] = {
            key + "_min_median_max": [f(r[key] for r in arm) for f in (min, median, max)]
            for key in ("shared_wall_seconds", "launcher_elapsed_wall_s")
        }
        for role in ROLE_LOGS:
            slopes = [r["clocks"][role]["observed_rate"] for r in arm]
            rate_summary[str(speed)][role] = {"matches": len(slopes), "min": min(slopes), "median": median(slopes),
                                              "max": max(slopes)}
            if role != "host":
                brackets = [r["clocks"][role]["opening_rate"] for r in arm]
                observed = [b["observed_rate"] for b in brackets if b["status"] == "bracketed"]
                rate_summary[str(speed)][role]["release_to_pickup_brackets"] = {
                    "status_counts": dict(Counter(b["status"] for b in brackets)),
                    "within_ten_percent": sum(.9 * speed <= v <= 1.1 * speed for v in observed),
                    "min_median_max": [f(observed) for f in (min, median, max)] if observed else None,
                }
    return dict(schema=1, schedule_sha256=sha(schedule_path), native_build_sha256=sha(build_path),
                prior_planner_qualification_sha256=sha(PRIOR), configuration=common,
                agreement_band_game_s=band, secondary_band_game_s=fine, rates=rate_summary,
                summary=summaries, pairs=pairs, runs=runs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--paths", type=Path, required=True, help="Private match directories in frozen schedule order")
    parser.add_argument("--output", type=Path, required=True, help="Write the comparison to a new JSON file")
    args = parser.parse_args()
    try:
        rows = [Path(s) for s in args.paths.read_text(encoding="utf-8").splitlines() if s.strip()]
        result = evaluate(rows)
        with args.output.open("x", encoding="utf-8", newline="\n") as out:
            json.dump(result, out, indent=2, allow_nan=False)
            out.write("\n")
    except (ValueError, TypeError, KeyError, OSError, IndexError) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
