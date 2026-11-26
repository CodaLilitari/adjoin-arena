"""Score physical play in the owning processes' game-clock windows for a map sweep."""
import argparse
from collections import Counter
import json
from pathlib import Path

from .competitive_results import fields, summarize
from .map_coverage import JHS_MAP, schedule

# Confirmed floors on the original JKL. The tall outdoor void in sector 5 has no upper floor.
JHS_REGIONS = {
    "middle": {19, 25, 26, 27, 28, 29, 30, 32, 51, 52, 53, 71, 72, 79, 80, 81, 82, 83, 120, 121, 123},
    "upper_passages": {34, 35, 36, 56, 57, 58, 84},
    "roof": {0, 2, 10, 11, 14, 46, 47, 48, 128, 166},
}
JHS_ASCENT = (124, 122, 121, 120, 123, 119, 58)


def owner_activity(lines, window, seconds, scope, is_jhs):
    start = window["first"]["game_ms"]
    end = start + 1000 * seconds
    sites, life_sites = set(), set()
    counts, objectives = Counter(), Counter()
    regions, ascent = {}, 0
    life = previous = previous_region = None
    alive = False
    seen_ground = False
    for line in lines:
        tag = line.partition(" ")[0]
        if tag not in ("BOT_RED_FIRST", "BOT_RED_STATE", "BOT_RED_NAV"):
            continue
        d = fields(line)
        if tag in ("BOT_RED_FIRST", "BOT_RED_STATE"):
            new_life = d["life"]
            alive = tag == "BOT_RED_FIRST" or (d["dead"] == "0" and float(d["hp"]) > 0)
            if not alive or new_life != life:
                life_sites.clear()
                seen_ground = False
                ascent = 0
                previous = previous_region = None
            life = new_life
            continue
        t = round(1000 * float(d["t"]))
        if not (start <= t < end and alive and d["scope"] == scope and int(d["sector"]) >= 0):
            continue
        sector = int(d["sector"])
        sites.add(sector)
        life_sites.add(sector)
        counts["max_distinct_sectors_one_life"] = max(counts["max_distinct_sectors_one_life"], len(life_sites))
        counts["alive_samples"] += 1
        counts["ready_movement_samples"] += bool(int(d["ready"]) and int(d["nodes"]) and int(d["edges"])
                                                 and abs(float(d["fwd"])) + abs(float(d["slide"])) > .01)
        counts["fire_samples"] += d["fire"] != "0,0"
        counts["same_life_sector_changes"] += previous is not None and sector != previous
        if int(d["objective_valid"]):
            objectives[d["objective"]] += 1
        if is_jhs:
            region = next((k for k, sectors in JHS_REGIONS.items() if sector in sectors), None)
            if region and region == previous_region:
                result = regions.setdefault(region, {"sectors": set(), "arrived_from_lower_in_life": False})
                result["sectors"].add(sector)
                result["arrived_from_lower_in_life"] |= seen_ground
            if sector in (5, 7, 107, 124, 135, 199):
                seen_ground = True
            previous_region = region
            if sector != previous:
                if ascent < len(JHS_ASCENT) and sector == JHS_ASCENT[ascent]:
                    ascent += 1
                else:
                    ascent = int(sector == JHS_ASCENT[0])
                counts["consecutive_ascent_sectors"] = max(counts["consecutive_ascent_sectors"], ascent)
        previous = sector
    for entry in regions.values():
        entry["sectors"] = sorted(entry["sectors"])
    return dict(counts, visited=sorted(sites), objectives=dict(objectives), jhs_regions=regions)


def score(directory, cell):
    receipt_file = directory / "receipt.json"
    if not receipt_file.exists():
        return {"status": "missing_receipt"}
    receipt = json.loads(receipt_file.read_bytes())
    row = summarize(directory)  # Rejects changed owner and server logs.
    if row["status"] != "live_join_and_loadout_verified":
        return row
    if any(row[key] != cell[key] for key in ("map", "map_sha256", "mode", "weapons", "force")):
        raise ValueError("Receipt differs from the scheduled map or rules")
    if receipt["mode_transfer"]["content"]["episode_sha256"] != cell["episode_sha256"]:
        raise ValueError("Episode digest differs from schedule")
    scope = "/".join((cell["mode"], cell["weapons"], "force" if cell["force"] == "on" else "noforce"))
    pace = receipt["pace_experiment"]
    both_active = True
    for side, owner in row["owners"].items():
        with (directory / (side + ".log")).open(errors="replace") as stream:
            activity = owner_activity(stream, pace["roles"][side], pace["requested_game_seconds"],
                                      scope, cell["map_sha256"] == JHS_MAP)
        active = bool(activity.get("ready_movement_samples") and
                      (activity.get("same_life_sector_changes") or owner.get("kills", 0) > 0 or owner.get("weapon_gains")))
        if cell["mode"] == "ctf":
            active = active and any(key != "none" for key in activity["objectives"])
        owner.update(activity=activity, active=active)
        both_active &= active
    row.update(both_active=both_active, game_seconds=pace["requested_game_seconds"])
    return row


def report(roots):
    cells = []
    for cell in schedule():
        attempts = []
        for root in roots:
            directory = root / cell["key"] / "match"
            if directory.parent.is_dir():
                attempts.append(dict(batch=root.name, **score(directory, cell)))
        cells.append(dict(**cell, attempts=attempts))
    return {"schema": 1, "counts": {"scheduled": len(cells),
            "attempted": sum(bool(c["attempts"]) for c in cells),
            "verified": sum(any(a["status"] == "live_join_and_loadout_verified" for a in c["attempts"]) for c in cells),
            "both_active": sum(any(a.get("both_active") for a in c["attempts"]) for c in cells)},
            "cells": cells}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("batch", type=Path, nargs="+")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    summary = report(args.batch)
    args.output.write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary["counts"]))
