"""Re-read native movement, match scores and learning checkpoints for the immediate-start study."""
import argparse
import json
from pathlib import Path
from statistics import median

from .native_duel import require, sha
from ..legacy.native_red_match import first_controls


def run(directory, cell, split):
    src = directory / "receipt.json"
    receipt = json.loads(src.read_bytes())
    red = receipt["red_policy"]
    pace = receipt["pace_experiment"]
    require(receipt["status"] == "live_join_and_loadout_verified" and
            receipt["kind"] == "adjoin-arena-stock-red-policy" and receipt["network_interfaces"] == ["lo"]
            and receipt["requested_map"] == cell["map"] and red["elite"], "Unexpected game or build")
    order = ["boba_fett","jan_ors"] if cell["first"] == "boba" else ["jan_ors","boba_fett"]
    require(receipt["seat_order"] == order and receipt["requested_match_seconds"] == 90,
            "Unexpected join order or duration")
    require(all(sha(directory / n) == h for n, h in receipt["log_sha256"].items()) and
            sha(directory / pace["trace"]) == pace["trace_sha256"], "Evidence hash mismatch")
    require(not any(k in receipt for k in ("opening_fixture","ready_gate_observations","planner_experiment")),
            "Unexpected gate or modified opening")
    control = first_controls(directory, receipt)
    require(control == red["start_and_outcomes"], "Native evidence changed")
    subject = red["model_side"]
    if cell["controller"] in ("model","teacher"):
        require(subject == (cell.get("subject") if cell["controller"] == "model" else None), "Unexpected learned seat")
    if subject is not None:
        require(subject == cell["subject"] and red["weights_sha256"], "Missing model identity")
    rates = {k:v["observed_rate"] for k,v in pace["roles"].items()}
    require(set(rates) == {"host","dark","light"} and all(1.8 <= v <= 2.2 for v in rates.values()), "Unqualified pace")
    seats = {}
    for side, owner in control["owners"].items():
        stats = owner["owner_state"]
        seats[side] = {"slot": receipt["bots"][side]["joined"]["slot"],
                       "join_to_eligible_wall_s": owner["join_to_eligible_wall_s"],
                       "first_movement_frames_after_eligible": owner["eligible_to_movement_frames"],
                       "first_movement_wall_s_after_eligible": owner["eligible_to_movement_wall_s"],
                       "teacher_labels": owner["teacher_labels"], "last_score": owner["last_native_score_sample"],
                       "final_score": {k:stats["last_state"][k] for k in ("kills","deaths")},
                       "weapon_bin_gains": len(stats["weapon_gains"])}
    return {"split":split,"name":cell["name"],"map":cell["map"],"first":cell["first"],
            "red_binary":red["build"]["binary_sha256"],"model_side":subject,"model_sha256":red["weights_sha256"],
            "source_receipt_sha256":sha(src),"log_sha256":receipt["log_sha256"],"clocks":rates,"seats":seats,
            "first_move_before_second_join_wall_s":control["first_seat_move_before_second_join_wall_s"]}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--runs", required=True, type=Path)
    p.add_argument("--design", required=True, type=Path)
    p.add_argument("--history", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--include-extension", action="store_true")
    args = p.parse_args()
    design = json.loads(args.design.read_bytes())
    history = json.loads(args.history.read_bytes())["matches"]
    phases = ["training"] + (["training_extension"] if args.include_extension else []) + ["test","stream_training"]
    rows = [run(args.runs / c["name"], c, phase) for phase in phases for c in design.get(phase,[])]
    require(len(set(r["source_receipt_sha256"] for r in rows)) == len(rows), "Repeated source match")
    learning = [r for r in rows if r["split"] != "test"]
    require([r["source_receipt_sha256"] for r in learning] == [r["receipt_sha256"] for r in history],
            "Learning stream differs from observed training and practice matches")
    require(len({r["red_binary"] for r in rows}) == 1, "Native build changed")
    for i, row in enumerate(learning):
        if row["split"] == "stream_training":
            require(row["model_sha256"] == history[i-1]["practice"], "Practice did not use the selected version")
    frames = [s["first_movement_frames_after_eligible"] for r in rows for s in r["seats"].values()]
    opening = [r["first_move_before_second_join_wall_s"] for r in rows]
    result = {"schema":1,"matches":rows,"rolling_history":history,
              "summary":{"matches":len(rows),"players":len(frames),"first_tick_movements":frames.count(0),
                         "max_frames_to_movement":max(frames),"first_seat_lead_wall_s_min_median_max":
                         [min(opening),median(opening),max(opening)]}}
    with args.output.open("x",encoding="utf-8") as out:
        json.dump(result,out,indent=2,allow_nan=False)
        out.write("\n")


if __name__ == "__main__":
    main()
