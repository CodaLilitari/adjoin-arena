"""Evaluate the paired normal-policy and start-on-GO Canyon Oasis trials."""
import argparse
import json
from pathlib import Path
from statistics import median

from .native_duel import require, sha
from .opening_detour import read_opening_detour
from .start_crossover import read_match


SCHEDULE = Path(__file__).resolve().parents[3] / "qa/adjoin-arena-planner-start-schedule.json"
CANONICAL_BUILD = Path(__file__).resolve().parents[3] / "native/planner-go-build.json"
EXPECTED = {41: (29, "concussion_rifle"), 18: (34, "repeater")}
FIRST_PROFILE = {"boba": "boba_fett", "jan": "jan_ors"}


def evidence(directory, cell):
    match, fixture, config = read_match(directory, allow_no_plan=True)
    receipt = json.loads((directory / "receipt.json").read_bytes())
    experiment = receipt["planner_experiment"]
    require(config["seat_order"][0] == FIRST_PROFILE[cell["first"]]
            and match["assignment"] == cell["starts"] and experiment["mode"] == cell["mode"],
            "Run does not match its scheduled join order, layout or planner mode")
    require(config["requested_match_seconds"] == 22, "Unexpected match length")
    config.pop("seat_order")
    research = config.pop("planner_experiment")
    config["research_build"] = research["build"]
    binary = research["build"]
    require(binary == json.loads(CANONICAL_BUILD.read_bytes()), "Run used a different research build")
    game_hashes = config["binary_and_map_hashes"]
    host_image = {"executable_sha256": game_hashes["bin/linux-x86_64/openjkdf2"],
                  "networking_library_sha256": game_hashes["bin/linux-x86_64/libGameNetworkingSockets.so"]}
    bot_image = {"executable_sha256": binary["binary_sha256"], "networking_library_sha256": binary["gns_sha256"]}
    require(experiment["loaded_images"] == {"server": host_image, "dark": bot_image, "light": bot_image},
            "Loaded native executables or networking libraries differ from the measured build")
    config["observed_process_images"] = experiment["loaded_images"]
    config["initial_force_stars"] = {side: agent["first_stars"] for side, agent in receipt["bots"].items()}
    require(config["initial_force_stars"]["dark"] != config["initial_force_stars"]["light"],
            "Distinct Force profiles required")
    owners = []
    for side, seat in match["seats"].items():
        native = experiment["owners"][side]
        require(native == receipt["ready_gate_observations"]["owners"][side]["planner"],
                "Recorded native planner evidence disagrees with qualified owner log")
        expected_item, weapon = EXPECTED[seat["sector"]]
        first = seat["first_plan_item"]
        gains = seat["first_life_gain_seconds_after_release"]
        trace = read_opening_detour(directory / (side + ".log"), seat["name"], first, gains)
        require(native["first_gear_plan_after_release"] == (None if first is None else not seat["first_plan_during_hold"]),
                "Native planner and initial gear evidence disagree")
        owners.append({"slot": seat["slot"], "player": seat["name"], "side": side, "sector": seat["sector"],
                       "expected_item": expected_item, "initial_item": first,
                       "initial_target_correct": first == expected_item,
                       "owner_hold_seconds": seat["held_owner_seconds"],
                       "gain_seconds_from_release": gains, "expected_weapon_gain_s": gains[weapon],
                       "respawns": seat["observed_respawns"], "planner": native,
                       "pickup_evidence_status": trace["status"], "pickup_evidence_reason": trace["reason"],
                       "pickup": trace["pickup"],
                       "different_target_after_release": trace["post_release_different_item_plan_before_pickup"],
                       "plans_before_pickup": [{"item": q["item"], "direct": q["direct"], "after_release": q["after_release"]}
                                               for q in trace["plans"]]})
    owners.sort(key=lambda v: v["slot"])
    row = {"index": cell["index"], "set": cell["set"], "block": cell["block"], "mode": cell["mode"],
           "first": cell["first"], "starts": cell["starts"], "receipt_sha256": match["source_receipt_sha256"],
           "logs_sha256": match["logs_sha256"], "video": match["video"],
           "shared_wall_s": match["shared_observation_wall_seconds"], "ack_spread_ms": match["host_ack_spread_ms"],
           "owners": owners}
    return row, config, fixture


def summarize(rows, slot):
    owners = [r["owners"][slot - 1] for r in rows]
    observed = [o for o in owners if o["initial_target_correct"] and o["pickup_evidence_status"] == "qualified"]
    times = [o["expected_weapon_gain_s"] for o in owners if o["expected_weapon_gain_s"] is not None]
    return {"openings": len(owners), "correct_initial_target": sum(o["initial_target_correct"] for o in owners),
            "corroborated_expected_pickup": len(observed),
            "post_release_detours": sum(o["different_target_after_release"] for o in observed),
            "expected_weapon_gains": len(times), "median_expected_gain_s": median(times) if times else None,
            "min_expected_gain_s": min(times, default=None), "max_expected_gain_s": max(times, default=None)}


def evaluate(directories, schedule_path=SCHEDULE):
    schedule = json.loads(schedule_path.read_bytes())["runs"]
    require(len(directories) == len(schedule) == 18, "Supply sixteen main and two confirmation matches")
    common = None
    fixtures = {}
    runs = []
    for directory, cell in zip(directories, schedule, strict=True):
        row, config, fixture = evidence(directory, cell)
        if common is None:
            common = config
        require(config == common, "Build, server, player profiles or other matched settings differ")
        require(fixtures.setdefault(cell["starts"], fixture) == fixture, "Fixture changed within one layout")
        runs.append(row)
    require(len({r["logs_sha256"]["server.log"] for r in runs}) == len(runs), "Reused native match")
    summaries = []
    for phase in ("main", "held_out"):
        for mode in ("off", "on"):
            chosen = [r for r in runs if r["set"] == phase and r["mode"] == mode]
            require(len(chosen) == (8 if phase == "main" else 1), "Incomplete main or confirmation condition")
            summary = {"set": phase, "mode": mode, "first_seat": summarize(chosen, 1),
                       "second_seat": summarize(chosen, 2)}
            if phase == "main":
                summary["first_seat_by_player"] = {
                    first: summarize([r for r in chosen if r["first"] == first], 1) for first in FIRST_PROFILE}
            summaries.append(summary)
    return {"schema": 1, "schedule_sha256": sha(schedule_path), "configuration": common,
            "fixtures": fixtures, "summary": summaries, "runs": runs}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--paths", type=Path, required=True, help="One private match directory per line in schedule order")
    parser.add_argument("--output", type=Path, required=True, help="New comparison JSON")
    args = parser.parse_args()
    try:
        lines = args.paths.read_text(encoding="utf-8").splitlines()
        data = evaluate([Path(s) for s in lines if s.strip()])
        with args.output.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(data, stream, indent=2, allow_nan=False)
            stream.write("\n")
    except (OSError, KeyError, ValueError, IndexError, TypeError) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
