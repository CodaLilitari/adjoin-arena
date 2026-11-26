"""Check both JKWeb owners and the optional same-room lobby entry in original JHS runs."""
import argparse
import json
import math
from pathlib import Path
import re
import struct

from .jhs_upper_play import digest
from ..map_coverage import JHS_GOB, JHS_MAP


def fields(line):
    return dict(re.findall(r"(\w+)=([^\s]+)", line))


def owner(directory, seat, host):
    path = directory / f"{seat}.console.log"
    lines = path.read_text(encoding="utf8", errors="replace").splitlines()
    def record(marker):
        matches = [fields(s) for s in lines if " " + marker + " " in s]
        if len(matches) != 1:
            raise ValueError(f"Expected one {seat} {marker}")
        return matches[0]
    joined = record("BOT_JOINED")
    setup = record("BOT_WEB_HOST" if seat == host else "BOT_WEB_EXTERNAL")
    behavior = record("BOT_BEHAVIOR")
    name = behavior["name"]
    status = []
    for line in lines:
        if " BOT_STATUS " in line:
            values = fields(line)
            if values["name"] == name:
                status.append((float(line.split()[0]), values))
    local = json.loads((directory / seat / "run.json").read_bytes())
    room = local.get("hosted") or local["external"]
    if (room["episode_sha256"], room["map_sha256"]) != (JHS_GOB, JHS_MAP):
        raise ValueError("Unverified owner content")
    rules = local["mode"]
    if joined["map"] != "jhs.jkl" or setup["episode"].lower() != "jhs" or setup["map"] != "jhs.jkl":
        raise ValueError("Owner loaded unexpected content")
    ff = rules.startswith("ff-")
    if int(setup["rank"]) != (8 if ff else 0) or behavior["force_enabled"] != str(int(ff)):
        raise ValueError("Owner Force policy differs from negotiated host rank")
    if behavior["sabers_only"] != str(int(rules.endswith("-sabers"))):
        raise ValueError("Owner weapon policy differs from the scheduled endpoint")
    return status, dict(slot=int(joined["slot"]), network_id=int(joined["net"]), name=name,
                        negotiated_rank=int(setup["rank"]), rules=rules, sabers_only=int(behavior["sabers_only"]),
                        force_enabled=int(behavior["force_enabled"]), console_sha256=digest(path))


def score(path):
    manifest, = path.glob("room/headless-*/headless.json")
    main = json.loads(manifest.read_bytes())
    hosted = main["hosted"]
    if (hosted["episode_sha256"], hosted["map_sha256"]) != (JHS_GOB, JHS_MAP):
        raise ValueError("Expected original JHS")
    if set(main["seats"]) != {"red", "lily"} or not all(v["joined"] for v in main["seats"].values()):
        raise ValueError("Expected two joined owners")
    observations, seats = {}, {}
    for key in main["seats"]:
        observations[key], seats[key] = owner(manifest.parent, key, hosted["seat"])
    if any(len({s[field] for s in seats.values()}) != 2 for field in ("network_id","slot")):
        raise ValueError("Conflicting owner identities")
    rules = seats["lily"]["rules"]
    if seats["red"]["rules"] != rules:
        raise ValueError("Owners disagree on endpoint")
    # Use only periodic samples entirely within the shared wall-time window.
    start = max(rows[0][0] for rows in observations.values())
    end = min(rows[-1][0] for rows in observations.values())
    for key, rows in observations.items():
        interval = [(w,s) for w,s in rows if start <= w <= end]
        if len(interval) < 2:
            raise ValueError("Too few overlapping periodic owner samples")
        first, last = interval[0], interval[-1]
        rate = (float(last[1]["t"])-float(first[1]["t"])) / (last[0]-first[0])
        def position(sample):
            return tuple(map(float, sample["pos"].split(",")))
        moves = changes = 0
        for (_,a), (_,b) in zip(interval, interval[1:]):
            if min(float(a["health"]),float(b["health"])) > 0 and a["deaths"] == b["deaths"]:
                moves += math.dist(position(a),position(b)) > .02
                changes += a["sector"] != b["sector"]
        sectors = sorted({int(s["sector"]) for _,s in interval if float(s["health"]) > 0})
        seats[key].update(game_per_wall=round(rate,4), native_status_samples=len(interval),
                          living_motion_intervals=moves, same_life_sector_changes=changes, sectors=sectors)
    entry = path / "lobby-entry.bin"
    lobby = None
    if entry.exists():
        raw = entry.read_bytes()
        if len(raw) != 240 or raw[88:120].split(b"\0")[0].lower() != b"jhs" or raw[120:152].split(b"\0")[0].lower() != b"jhs.jkl":
            raise ValueError("Unexpected JHS wire entry")
        flags, tick, rank = struct.unpack_from("<iii",raw,228)
        if rank != seats["red"]["negotiated_rank"]:
            raise ValueError("Lobby and joined rank disagree")
        lobby = dict(multiModeFlags=flags, teams_enabled=bool(flags&1), tick_ms=tick, rank=rank, entry_sha256=digest(entry))
    active = all(.85 <= v["game_per_wall"] <= 1.15 and v["living_motion_intervals"] > 0 and v["same_life_sector_changes"] > 0 for v in seats.values())
    return dict(trial=path.name, rules=rules, sha256_wasm=digest(path/"binary/openjkdf2.wasm"),
                episode_sha256=JHS_GOB, map_sha256=JHS_MAP, lobby=lobby, overlapping_wall_seconds=[start,end],
                seats=seats, both_active=active, direct_ffa_two_active=bool(lobby and not lobby["teams_enabled"] and active))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("room", type=Path, nargs="+")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = {"schema": 1, "runs": [score(p) for p in args.room]}
    args.output.write_text(json.dumps(result, indent=2)+"\n", encoding="utf8")
