"""Summarize verified native matches inside each playing owner's paired game-clock window."""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re


def fields(line):
    return dict(token.split("=", 1) for token in line.split() if "=" in token)


def summarize(directory):
    receipt_bytes = (directory / "receipt.json").read_bytes()
    receipt = json.loads(receipt_bytes)
    row = {"run": directory.name, "receipt_sha256": hashlib.sha256(receipt_bytes).hexdigest(),
           "status": receipt["status"]}
    if receipt["status"] != "live_join_and_loadout_verified":
        return dict(row, failure=receipt.get("failure", receipt.get("error")))
    transfer = receipt["mode_transfer"]
    owners = {}
    row.update(seats=receipt["seat_order"], map=transfer["content"]["map"], map_sha256=transfer["content"]["map_sha256"],
               mode=transfer["mode"], weapons=transfer["weapons"], force=transfer["force"],
               client_sha256=receipt["red_policy"]["build"]["binary_sha256"], rate=receipt["pace_experiment"]["speed"],
               controls=receipt.get("competitive_controls"), model_side=receipt["red_policy"]["model_side"],
               model_sha256=receipt["red_policy"]["weights_sha256"], owners=owners)
    for role in ("dark", "light", "host"):
        window = receipt["pace_experiment"]["roles"][role]
        start = window["first"]["game_ms"]
        end = start + 1000 * receipt["pace_experiment"]["requested_game_seconds"]
        log = "server.log" if role == "host" else role + ".log"
        data = (directory / log).read_bytes()
        if hashlib.sha256(data).hexdigest() != receipt["log_sha256"][log]:
            raise ValueError(f"{directory} {log}: digest mismatch")
        lines = data.decode("ascii", errors="replace").splitlines()
        if role == "host":
            if transfer["mode"] == "ctf":
                captures = {"red": 0, "gold": 0}
                clock = None
                for line in lines:
                    if line.startswith("ARENA_PACE "):
                        clock = int(fields(line)["game_ms"])
                    match = re.fullmatch(r"(Red|Gold) Team Captured The Flag!", line.strip(), re.I)
                    if match and clock is not None and start <= clock < end:
                        captures[match[1].lower()] += 1
                row["host_captures"] = captures
            continue
        counts = Counter()
        sites = set()
        previous = initial = last = None
        last_pose = None
        t_ms = -1
        for line in lines:
            tag = line.partition(" ")[0]
            if tag not in ("BOT_RED_STATE", "BOT_RED_NAV", "BOT_DUEL", "BOT_FORCE_INPUT", "BOT_SABER_POSE"):
                continue
            d = fields(line)
            if "game_ms" in d:
                t_ms = int(d["game_ms"])
            elif "t" in d:
                t_ms = round(1000 * float(d["t"]))
            if t_ms >= end:
                continue
            if tag == "BOT_RED_STATE":
                state = tuple(int(d[k], 0) for k in ("kills", "deaths", "life", "dead", "weapons"))
                if t_ms >= start:
                    initial = initial or previous or state
                    last = state
                    if previous and previous[2] == state[2] and not (previous[3] or state[3]):
                        counts["weapon_gains"] += (state[4] & ~previous[4]).bit_count()
                previous = state
            elif t_ms < start:
                continue
            elif tag == "BOT_SABER_POSE":
                xy = tuple(map(float, d["xy"].split(",")))
                if (last_pose and last_pose[0] + 1 == int(d["frame"]) and last_pose[1] == d["life"]
                        and last_pose[2] and d["dead"] == "0"):
                    distance = math.dist(last_pose[3], xy)
                    if distance <= .3:
                        counts["saber_fire_frame_pairs"] += 1
                        counts["saber_fire_frames_xy_over_0.001_units"] += distance > .001
                last_pose = (int(d["frame"]), d["life"], d["fire"] != "0,0" and d["dead"] == "0", xy)
                if d["dead"] == "0" and d["foe"] != "-1" and d["fire"] != "0,0":
                    dz = float(d["foe_z"]) - float(d["z"])
                    if dz > .1 and float(d["foe_vz"]) > .1:
                        counts["rising_higher_foe_fire_frames"] += 1
                        counts["rising_higher_foe_fire_frames_positive_pitch"] += float(d["pitch"]) > 0
            elif tag == "BOT_RED_NAV":
                sites.add(int(d["sector"]))
                if d["weapon"] == "10" and d["fire"] != "0,0":
                    counts["sampled_saber_fire"] += 1
                    counts["sampled_saber_fire_with_move_input"] += abs(float(d["fwd"])) + abs(float(d["slide"])) > .01
            elif tag == "BOT_DUEL":
                counts["duel_labels"] += 1
                if d["model"] != "teacher":
                    counts["model_label_" + d["selected"]] += 1
            elif tag == "BOT_FORCE_INPUT" and d["bin"] == "29":
                counts["protection_inputs"] += 1
        if not initial or not last:
            raise ValueError(f"{directory} {role}: no score snapshots in the observed game-clock window")
        owners[role] = dict(kills=last[0] - initial[0], deaths=last[1] - initial[1], sectors=len(sites),
                            **dict(counts), stars=receipt["bots"][role]["first_stars"])
    return row


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directories", nargs="+", type=Path, help="One match output directory per argument.")
    args = parser.parse_args()
    print(json.dumps([summarize(d) for d in args.directories], indent=2))
