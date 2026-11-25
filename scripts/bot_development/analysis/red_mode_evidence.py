"""Verify scheduled native mode trials and produce a portable gameplay receipt."""
import argparse
from collections import Counter
import json
from pathlib import Path
import re

from .native_duel import require, sha
from ..legacy.native_mode_transfer import read_native
from ..legacy.native_red_match import first_controls, read_owner


def load(path):
    return json.loads(path.read_bytes())


def missing_motion(directory, match, qualification):
    """Keep a full scheduled match where an authenticated player never moved."""
    owners, missing = {}, []
    for side in ("dark", "light"):
        owner = read_owner(directory / (side + ".log"))
        events = owner["events"]
        join, first = events["BOT_RED_JOIN"], events["BOT_RED_FIRST"]
        pid = match["pace_experiment"]["loaded_images"][side]["pid"]
        require(int(join["pid"]) == int(first["pid"]) == pid and int(first["frame"]) == 1
                and int(join["slot"]) == match["bots"][side]["joined"]["slot"], "Invalid first native tick")
        owner["join_to_eligible_wall_s"] = (int(first["mono_ns"]) - int(join["mono_ns"])) / 1e9
        if "BOT_RED_APPLY" not in events:
            missing.append(side)
        owners[side] = owner
    require(missing and set(qualification["qualification_errors"]) ==
            {side + "_navigation_unobserved" for side in missing}, "Unexplained native control failure")
    return {"owners": owners, "first_seat_move_before_second_join_wall_s": None}, missing


def verify_match(directory, spec, retain_control_failure=False):
    source = directory / "receipt.json"
    match = load(source)
    config = match["mode_transfer"]
    clock = match["pace_experiment"]
    require(match["network_interfaces"] == ["lo"], "Match used a different network")
    first = "jan_ors" if spec["first"] == "jan" else "boba_fett"
    require(match["seat_order"][0] == first and match["requested_map"] == spec["map"] and
            config["content"]["episode"] == spec.get("episode", "C09").upper() and
            config["content"]["map_sha256"] == spec["map_sha256"] and
            config["mode"] == spec["mode"] and config["force"] == spec["force"] and
            config["weapons"] == {"saber": "sabers", "guns": "guns"}[spec["weapons"]],
            "Trial does not match the scheduled rules, owner order or map")
    require(sha(directory / clock["trace"]) == clock["trace_sha256"] and
            all(sha(directory / name) == digest for name, digest in match["log_sha256"].items()),
            "Changed clock trace or native log")
    require(clock["requested_game_seconds"] == spec["game_seconds"] and
            set(clock["roles"]) == {"host", "dark", "light"} and
            len({v["pid"] for v in clock["roles"].values()}) == 3 and
            all(abs(v["observed_rate"] - clock["speed"]) <= 0.1 * clock["speed"]
                for v in clock["roles"].values()), "Unverified native clock")
    rules = read_native(directory, match)
    missing = []
    if retain_control_failure and match.get("error") == "native_red_missing_immediate_start_evidence":
        controls, missing = missing_motion(directory, match, rules)
    else:
        controls = first_controls(directory, match)
        require(not rules["qualification_errors"], str(rules["qualification_errors"]))
    if config["content"]["episode"] not in ("JK1MP", "JK1CTF"):
        require(all("custom_admission" in state for state in rules["owners"].values()),
                "Missing evidence that the custom map was admitted before play")
    media = "not_requested"
    if match.get("observer_receipt"):
        path = directory / match["observer_receipt"]
        require(sha(path) == match["observer_receipt_sha256"], "Changed observer receipt")
        observer = load(path)
        media = observer["status"]
        if media == "recorded":
            video = observer["video"]
            require(video["decoded_fully"] and sha(path.parent / video["path"]) == video["sha256"],
                    "Missing or changed video")
    recovered = not missing and match["status"] != "live_join_and_loadout_verified"
    if recovered:
        recovery = load(directory / "gameplay-audit.json")
        require(recovery["status"] == "gameplay_qualified_media_failed" and
                recovery["source_receipt_sha256"] == sha(source) and
                recovery["first_controls"] == controls and media != "recorded",
                "Unresolved match failure")
    host = (directory / "server.log").read_text(errors="replace")
    require(all(name + " has joined the game" in host for name in ("Bot_BobaFett", "Bot_JanOrs")),
            "Missing native host joins")
    captures = Counter(re.findall(r"\b(red|gold) team captured the flag!", host.lower()))
    owners = {}
    for side, state in rules["owners"].items():
        player = controls["owners"][side]
        contexts = [c for c in state["contexts"] if c["map_sha"] == spec["map_sha256"]]
        owners[side] = {
            "native_scope": contexts[-1]["scope"], "teams": state["teams"], "nodes": int(contexts[-1]["nodes"]),
            "map_sectors": int(contexts[-1]["sectors"]), "visited_sectors": len(state["sectors"]),
            "graph_ready": state["graph_ready"], "movement_seen": state["movement_seen"],
            "previous_edges_loaded": max(int(c["loaded_edges"]) for c in contexts),
            "nav_events": state["cache_and_navigation_events"], "objectives": state["valid_objectives"],
            "effective_duel_models": state["effective_duel_models"], "labels": player["teacher_labels"],
            "join_to_first_eligible_wall_s": player["join_to_eligible_wall_s"],
            "flags": state["flags"], "carriers": state["carriers"]
        }
        if "custom_admission" in state:
            admission = state["custom_admission"]
            owners[side]["verified_custom_identity_before_control"] = {
                key: admission[key] for key in ("admission_line", "world_line", "first_control_line")
            }
    qualification = "completed_with_missing_horizontal_control" if missing else (
        "gameplay_verified_after_media_failure" if recovered else "verified")
    return {"name": spec["name"], "attempt": directory.name, "receipt_sha256": sha(source),
            "qualification": qualification, "missing_horizontal_control": missing,
            "map": spec["map"], "map_sha256": spec["map_sha256"], "episode_sha256": config["content"]["episode_sha256"],
            "build_sha256": match["red_policy"]["build"]["binary_sha256"], "first": first,
            "first_move_before_second_join_wall_s": controls["first_seat_move_before_second_join_wall_s"],
            "duration": spec["game_seconds"], "pace": clock["speed"], "measured_rates":
            {role: v["observed_rate"] for role,v in clock["roles"].items()}, "video": media,
            "policy_selection": {k: config["policy_selection"].get(k) for k in ("controller","reason","sha256")},
            "owners": owners, "stock_ctf_captures": dict(captures) if spec["mode"] == "ctf" else None}


def summarize(root, design_path, attempts_path, retain_control_failures=False):
    design = load(design_path)
    schedule = design["matrix"] + design["unseen"]
    attempts = load(attempts_path) if attempts_path else [
        {"name": spec["name"], "scheduled": spec["name"], "status": "qualified"} for spec in schedule
    ]
    rows, other_attempts = [], []
    for spec in schedule:
        name = spec["name"]
        eligible = []
        for entry in (a for a in attempts if a["scheduled"] == name):
            directory = root / entry["name"]
            require(directory.resolve().parent == root.resolve(), "Unexpected attempt directory")
            if entry["status"] == "qualified" or (directory / "gameplay-audit.json").is_file():
                eligible.append(directory)
            else:
                other_attempts.append({"name": directory.name, "status": entry["status"],
                                       "receipt_sha256": sha(directory / "receipt.json")
                                       if (directory / "receipt.json").is_file() else None})
        if not eligible and retain_control_failures:
            eligible = [root / name]
        require(len(eligible) == 1, f"{name} has {len(eligible)} qualified attempts")
        result = verify_match(eligible[0], spec, retain_control_failures)
        if spec.get("episode", "C09").upper() not in ("JK1MP", "JK1CTF"):
            require(result["episode_sha256"] == design["custom_episode_sha256"], "Wrong custom episode")
        rows.append(result)
    require(len({r["receipt_sha256"] for r in rows}) == len(rows), "Duplicate result")
    used = {r["attempt"] for r in rows}
    return {"schema": 1, "schedule_sha256": sha(design_path), "matches": rows,
            "other_attempts": [a for a in other_attempts if a["name"] not in used]}


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    for arg in ("runs", "schedule", "output"):
        cli.add_argument("--" + arg, required=True, type=Path)
    cli.add_argument("--attempts", type=Path, help="Optional attempt ledger when a scheduled trial was retried.")
    cli.add_argument("--retain-control-failures", action="store_true",
                     help="Report complete scheduled games with verified joins but missing horizontal control as failures.")
    args = cli.parse_args()
    result = summarize(args.runs, args.schedule, args.attempts, args.retain_control_failures)
    with args.output.open("x", encoding="utf-8", newline="\n") as out:
        json.dump(result, out, indent=2, allow_nan=False)
        out.write("\n")
