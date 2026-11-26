"""Count distinct native / JKWeb map and ruleset cells with measured owner evidence."""
import argparse
import hashlib
import json
from pathlib import Path


def read(path):
    raw = path.read_bytes()
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def score(native_path, browser_path, jhs_path=None):
    native, native_sha = read(native_path)
    browser, browser_sha = read(browser_path)
    rows = {}
    native_active_by_client = {}
    for cell in native["cells"]:
        key = cell["key"]
        if key in rows:
            raise ValueError(f"Duplicate scheduled cell {key}")
        attempts = [a for a in cell["attempts"] if a["status"] == "live_join_and_loadout_verified"]
        for digest in {a["client_sha256"] for a in attempts if a.get("both_active")}:
            native_active_by_client[digest] = native_active_by_client.get(digest, 0) + 1
        rows[key] = dict(native_verified=bool(attempts), native_active=any(a.get("both_active") for a in attempts),
                         browser_verified=False, browser_active=False, browser_team_goals=False,
                         native_team_goals=any(len(a["owners"])==2 and all(
                             any(k not in ("join", "none", "air") and n > 0 for k,n in s["activity"]["objectives"].items())
                             for s in a["owners"].values()) for a in attempts) if cell["mode"]=="ctf" else False,
                         native_capture=any(sum(a.get("host_captures",{}).values()) > 0 for a in attempts),
                         browser_capture=False)

    for attempt in browser["coverage"]:
        level = Path(attempt["map"]).stem
        force,weapons = attempt["rules"].split("-")
        if force not in ("nf","ff") or weapons not in ("guns","sabers") or browser["episode"].upper()!="JK1CTF":
            raise ValueError("Unexpected browser CTF condition")
        key = f"{level}-ctf-{weapons}-{'on' if force=='ff' else 'off'}"
        if key not in rows:
            raise ValueError(f"Browser trial outside the matrix: {key}")
        row = rows[key]
        owners = list(attempt["seats"].values())
        verified = (len(owners) == 2 and len({s["network_id"] for s in owners}) == 2
                    and len({s["slot"] for s in owners}) == 2 and all(
                        s["negotiated_rank"] == (8 if force=="ff" else 0) and .85 <= s["game_per_wall"] <= 1.15
                        for s in owners))
        if verified:
            row["browser_verified"] = True
            row["browser_active"] |= all(s["observed_living_motion_intervals"] > 0 and
                                         s["sectors_seen_in_native_status"] > 1 for s in owners)
            row["browser_team_goals"] |= all(s["requested_team"] in s["actual_team_reports"] and
                                             s["team_objectives"] for s in owners) and {s["requested_team"] for s in owners} == {1,2}
            row["browser_capture"] |= sum(attempt["captures_seen_by_both_owners"].values()) > 0

    sources = {native_path.name:native_sha, browser_path.name:browser_sha}
    jhs_trials = {}
    if jhs_path is None:
        jhs_path = native_path.with_name("jhs-ffa-owners.json")
    if jhs_path.is_file():
        jhs, sources[jhs_path.name] = read(jhs_path)
        scheduled = {cell["key"]:cell for cell in native["cells"]}
        for attempt in jhs["runs"]:
            force, weapons = attempt["rules"].split("-")
            key = f"jhs-ffa-{weapons}-{'on' if force == 'ff' else 'off'}"
            cell = scheduled[key]
            if (force not in ("nf","ff") or weapons not in ("sabers","guns") or
                    any(attempt[k] != cell[k] for k in ("episode_sha256","map_sha256"))):
                raise ValueError("JHS browser content or rules differ from the original scheduled cell")
            owners = list(attempt["seats"].values())
            rank = 8 if force == "ff" else 0
            start, end = attempt["overlapping_wall_seconds"]
            joined = (end > start and len(owners) == 2 and len({o["slot"] for o in owners}) == 2 and
                      len({o["network_id"] for o in owners}) == 2 and all(
                          o["rules"] == attempt["rules"] and o["negotiated_rank"] == rank and
                          o["sabers_only"] == (weapons == "sabers") and o["force_enabled"] == (force == "ff") and
                          .85 <= o["game_per_wall"] <= 1.15 for o in owners))
            lobby = attempt["lobby"]
            verified = bool(joined and lobby and lobby["rank"] == rank and
                            not lobby["teams_enabled"] and not (lobby["multiModeFlags"] & (1 | 8)))
            moving = joined and all(o["living_motion_intervals"] > 0 and o["same_life_sector_changes"] > 0
                                    for o in owners)
            rows[key]["browser_verified"] |= verified
            rows[key]["browser_active"] |= verified and moving
            jhs_trials[attempt["trial"]] = dict(key=key, verified_ffa=verified, both_moving=moving,
                                                verified_ffa_both_moving=verified and moving)
    ctf = [v for k,v in rows.items() if "-ctf-" in k]
    return {"schema":1, "sources":sources, "counts":{
        "distinct_scheduled":len(rows),
        "distinct_verified_either_runtime":sum(s["native_verified"] or s["browser_verified"] for s in rows.values()),
        "distinct_both_active_either_measurement":sum(s["native_active"] or s["browser_active"] for s in rows.values()),
        "ctf_distinct_scheduled":len(ctf), "ctf_distinct_both_active":sum(s["native_active"] or s["browser_active"] for s in ctf),
        "ctf_distinct_both_selected_flag_objectives":sum(s["native_team_goals"] or s["browser_team_goals"] for s in ctf),
        "ctf_distinct_with_a_capture":sum(s["native_capture"] or s["browser_capture"] for s in ctf)},
        "conditions":"One row per map/mode/weapons/Force combination. The native lane uses its published movement criterion. A browser activity pass requires sampled living motion from both owners and multiple periodic native sectors per owner. Flag objectives exclude entry, air and idle. A browser capture must be seen by both owners; a native capture is a stock host announcement.",
        "native_active_cells_by_client_sha256":dict(sorted(native_active_by_client.items())),
        "jhs_browser_trials":jhs_trials,
        "cells":rows}


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native",type=Path,default=Path("qa/map-rules-play.json"))
    parser.add_argument("--browser",type=Path,default=Path("qa/windows-stock-ctf-c2-c3.json"))
    parser.add_argument("--jhs-browser",type=Path,default=Path("qa/jhs-ffa-owners.json"))
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    result=score(args.native,args.browser,args.jhs_browser)
    args.output.write_bytes((json.dumps(result,indent=2)+"\n").encode())
    print(json.dumps(result["counts"]))

