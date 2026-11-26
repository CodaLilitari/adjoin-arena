"""Score C3 matched starts using each player's local COG observations."""
import argparse
from collections import Counter
from dataclasses import dataclass
from hashlib import sha256
import json
import math
from pathlib import Path
import re


# Portals and door-thing sectors from the original C3 JKL. Each triple is
# ordered chamber-side, door sector, far side. Turning back inside a doorway
# or leaving by another corridor does not complete that passage.
DOORS = {
    "lily": {"74_inner": (509, 507, 508), "73_outer": (510, 506, 511)},
    "red": {"24_locked_red": (396, 394, 395), "25_friendly_gold": (402, 401, 400)},
}
STARTS = {
    "lily": (0, 1, 505, (-5.612, -.563, 2.370)),
    "red": (1, 2, 393, (-2.046, -1.758, 2.620)),
}
ENEMY_FLAGS = {
    "lily": (693, (2.935669, -.050109, -1.231411)),
    "red": (700, (-4.913801, -1.597605, -1.306411)),
}
CONSOLE = re.compile(r"^\s*([\d.]+) (\w+) (.*)$")
DENIAL = re.compile(r"You need the (Red|Gold) key\.\.\.", re.I)
CAPTURE = re.compile(r"(Red|Gold) Team Captured The Flag\s*!", re.I)
FLAG_RETURN = re.compile(r"(Red|Gold) Flag (?:has (?:been )?)?returned\s*!", re.I)


@dataclass(frozen=True)
class Observation:
    kind: str
    wall: float
    slot: int
    team: int
    time: float
    sector: int
    position: tuple
    look: tuple
    health: float
    keys: tuple
    flags: tuple


def vector(text):
    # The JK console clips PrintVector at 30 characters. On C3 this can
    # remove the closing bracket after the third coordinate.
    clipped = len(text) == 30 and re.fullmatch(r"<-?\d+\.\d{6} -?\d+\.\d{6} -?\d+\.\d{4,6}", text)
    if not ((text.startswith("<") and text.endswith(">")) or clipped):
        raise ValueError(f"Unexpected COG vector {text!r}")
    values = tuple(map(float, text[1:].removesuffix(">").split()))
    if len(values) != 3 or not all(map(math.isfinite, values)):
        raise ValueError("Expected a finite three-dimensional vector")
    return values


def owner_log(path):
    raw = path.read_bytes()
    console = [match.groups() for line in raw.decode("utf-8", errors="replace").splitlines()
               if (match := CONSOLE.fullmatch(line))]
    observations = []
    for i, (wall, stream, message) in enumerate(console):
        if stream != "log" or message not in ("C3_MATCH_START_V1", "C3_MATCH_OBS_V1", "C3_MATCH_NEWLIFE_V1"):
            continue
        values = [text for _, stream, text in console[i+1:i+12] if stream == "log"]
        if len(values) != 11:
            raise ValueError("Incomplete C3 fixture observation")
        slot, team, clock, sector, pos, look, hp, red_key, gold_key, red_flag, gold_flag = values
        observations.append(Observation(
            message, float(wall), int(slot), int(team), float(clock), int(sector),
            vector(pos), vector(look), float(hp),
            (int(red_key), int(gold_key)), (int(red_flag), int(gold_flag))))
    return sha256(raw).hexdigest(), console, observations


def first_life(seat, rows, cutoff=None):
    starts = [row for row in rows if row.kind == "C3_MATCH_START_V1"]
    if len(starts) != 1:
        raise ValueError(f"{seat} has {len(starts)} placement witnesses")
    start, = starts
    slot, team, sector, pose = STARTS[seat]
    keys = (1, 0) if team == 1 else (0, 1)
    if ((start.slot, start.team, start.sector) != (slot, team, sector)
            or math.dist(start.position, pose) > .006 or start.health <= 0
            or start.keys != keys or start.flags != (0, 0)):
        raise ValueError(f"{seat} start, life or inventory differs from the intended fixture: {start}")
    samples = rows[rows.index(start):]
    if any(a.time > b.time for a, b in zip(samples, samples[1:])):
        raise ValueError("Owner game clock decreased")
    live = []
    for row in samples:
        if row.kind == "C3_MATCH_NEWLIFE_V1" or (cutoff is not None and row.time >= cutoff) or row.health <= 0:
            break
        if (row.slot, row.team) != (slot, team):
            raise ValueError("Owner identity changed during the measured life")
        live.append(row)
    if not live:
        raise ValueError("No living observations of the placed player")
    return live


def route_score(seat, live):
    start = live[0]
    def elapsed(row):
        return round(row.time - start.time, 3)

    # Only the upper observation bound is exact for this sampling interval.
    history = []
    opening = []
    exits = None
    passages = {}
    for row in live:
        if exits is None and row.sector != start.sector:
            exits = {"to_sector": row.sector, "observed_by_game_s": elapsed(row)}
        if history and history[-1] == row.sector:
            continue
        history.append(row.sector)
        if len(opening) < 6:
            opening.append([row.sector, elapsed(row)])
        for door, chain in DOORS[seat].items():
            if tuple(history[-3:]) == chain and door not in passages:
                passages[door] = elapsed(row)
    # Sector 505 has exactly two exits. A living player beyond the two
    # approach sectors and two door sectors has cleared the friendly chamber,
    # even when the polling cadence misses its narrow intermediate sectors.
    chamber_exit = None
    if seat == "lily":
        chamber_exit = next((elapsed(row) for row in live if row.sector not in
                             (505, 509, 507, 510, 506)), None)
    enemy_sector, enemy_origin = ENEMY_FLAGS[seat]
    enemy_bin_offset = 1 if seat == "lily" else 0
    return dict(
        start_game_s=start.time, start_sector=start.sector, start_position=start.position,
        start_look=start.look, start_health=start.health, start_keys_83_84=start.keys,
        first_life_sampled_through_game_s=elapsed(live[-1]), first_life_distinct_sectors=len(set(history)),
        first_life_max_displacement_jku=round(max(math.dist(row.position, start.position) for row in live), 3),
        opening_sector_observations=opening,
        first_sector_exit=exits, chamber_clear_observed_by_game_s=chamber_exit,
        witnessed_door_passages_game_s=passages,
        closest_observed_enemy_flag_start_jku=round(min(math.dist(row.position, enemy_origin) for row in live), 3),
        enemy_flag_sector_observed=enemy_sector in history,
        carried_enemy_flag_observed_by_game_s=next((elapsed(r) for r in live if r.flags[enemy_bin_offset] > 0), None),
    )


def score_arm(arm):
    room, = (arm / "rooms").glob("headless-*/headless.json")
    manifest = json.loads(room.read_bytes())
    if (manifest["hosted"]["map"].lower() != "c3.jkl" or
            not all(manifest["seats"][s]["joined"] for s in STARTS)):
        raise ValueError("Expected two joined owners in a C3 room")
    launcher = [json.loads(line) for line in (arm / "launcher.log").read_text().splitlines()
                if line.startswith("{")]
    hosted, = [event for event in launcher if event.get("event") == "hosted" and event["joined"]]
    mode = hosted["mode"]
    if mode not in ("ff-guns", "ff-sabers"):
        raise ValueError("Expected a full Force room")
    playing, = [event for event in launcher if event.get("event") == "playing"]
    end = playing["t"] + playing["seconds"]
    snapshots = json.loads((arm / "samples.json").read_bytes())
    owners = {}
    for seat in STARTS:
        digest, console, rows = owner_log(room.parent / (seat + ".console.log"))
        slot, team, *_ = STARTS[seat]
        joined, = [float(wall) for wall, _, msg in console
                   if re.fullmatch(rf"BOT_JOINED slot={slot} net=\d+ map=c3\.jkl .*", msg)]
        if not any(msg.startswith("BOT_CTF_BINDINGS map=c3.jkl red_flag=43 gold_flag=48 ")
                   and f"team={team}" in msg.split() for _, _, msg in console):
            raise ValueError(f"Missing C3 flags and team binding for {seat}")
        selected = [r for r in rows if r.wall <= end]
        started = next((r for r in selected if r.kind == "C3_MATCH_START_V1"), None)
        if started is None:
            raise ValueError(f"No {seat} placement in the measured room")
        shared = [s for s in snapshots if all(k in s["seats"] for k in STARTS)]
        if len(shared) < 2 or shared[-1]["wall"] <= shared[0]["wall"]:
            raise ValueError("Missing paired owner clock observations")
        low, high = (s["seats"][seat]["game_time"] for s in (shared[0], shared[-1]))
        rate = (high-low) / (shared[-1]["wall"] - shared[0]["wall"])
        physical = [s["seats"][seat] for s in snapshots if seat in s["seats"]]
        previous = next((s for s in reversed(physical) if s["game_time"] < started.time), None)
        companion = [s for s in physical if s["game_time"] >= started.time]
        if not companion:
            raise ValueError("No physical owner samples")
        cutoff = next((s["game_time"] for s in companion if s["deaths"] > 0 or s["health"] <= 0), None)
        life = first_life(seat, selected, cutoff)
        timed_messages = [text for wall, stream, text in console
                          if stream == "log" and playing["t"] <= float(wall) <= end]
        matched_begin = max(playing["t"], started.wall)
        life_messages = [text for wall, stream, text in console if stream == "log"
                         and matched_begin <= float(wall) <= life[-1].wall]
        bracket = [{"offset_game_s": round(row["game_time"] - started.time, 3), "weapon": row["weapon"],
                    "deaths": row["deaths"]} for row in (previous, companion[0]) if row]
        enemy_bin = 1 if seat == "lily" else 0
        shared_living = [r for r in selected if r.team == team and r.health > 0 and r.wall >= playing["t"]]
        objective_events = Counter(int(m[1]) for wall, _, text in console if playing["t"] <= float(wall) <= end
                                   and (m := re.search(rf"BOT_OBJECTIVE .*? mode=(\d+) team={team}\b", text)))
        owners[seat] = route_score(seat, life) | dict(
            placement_relative_to_shared_play_wall_s=round(started.wall - playing["t"], 2),
            weapon_observations_around_placement=bracket,
            join_wall_s=joined, placement_wall_s=started.wall,
            shared_owner_game_clock_s=[round(low, 3), round(high, 3)],
            shared_owner_game_span_s=round(high-low, 3), shared_game_s_per_wall_s=round(rate, 3),
            held_weapons_shared=sorted({s["seats"][seat]["weapon"] for s in shared}),
            candidate_bound_six=any("BOT_C3_ACCESS " in msg and "event=bind doors=6" in msg for _, _, msg in console),
            console_sha256=digest,
            matched_first_life_key_denials=dict(Counter(m[1].lower() for text in life_messages
                                                        if (m := DENIAL.fullmatch(text)))),
            shared_native_objective_modes=dict(objective_events),
            shared_observed_enemy_flag_in_inventory=any(r.flags[enemy_bin] > 0 for r in shared_living),
            shared_flag_returns_announced=dict(Counter(m[1].lower() for text in timed_messages
                                                       if (m := FLAG_RETURN.fullmatch(text)))),
            shared_key_denials=dict(Counter(m[1].lower() for text in timed_messages if (m := DENIAL.fullmatch(text)))),
            shared_capture_announcements=dict(Counter(m[1].lower() for text in timed_messages
                                                      if (m := CAPTURE.fullmatch(text)))),
        )
    for seat, other in (("lily", "red"), ("red", "lily")):
        owners[seat]["placement_after_opponent_join_wall_s"] = round(
            owners[seat]["placement_wall_s"] - owners[other]["join_wall_s"], 2)
    skew = abs(owners["lily"]["placement_wall_s"] - owners["red"]["placement_wall_s"])
    return dict(mode=mode, requested_shared_wall_s=playing["seconds"], placement_skew_wall_s=round(skew, 2),
                owners=owners, shared_captures={
        team: min(s["shared_capture_announcements"].get(team, 0) for s in owners.values())
        for team in ("red", "gold")})


def score_suite(folder):
    from .c3_door_stalls import EPISODE_SHA, MAP_SHA
    fixture = json.loads((folder / "fixture.json").read_bytes())
    comparison = json.loads((folder / "comparison.json").read_bytes())
    if (fixture["episode_sha256"] != comparison["fixture"] or fixture["stock_episode_sha256"] != EPISODE_SHA
            or fixture["map_sha256"] != MAP_SHA):
        raise ValueError("Matched fixture, stock episode or C3 map disagrees")
    arms = {}
    for item in comparison["arms"]:
        sub = folder / item["private_arm"]
        if sub.resolve().parent != folder.resolve():
            raise ValueError("Unexpected arm folder")
        arm = score_arm(sub)
        key = (arm["mode"], item["lane"])
        if (item["rules"] != arm["mode"] or key in arms or item["requested_seconds"] != arm["requested_shared_wall_s"]
                or any(not .85 <= s["shared_game_s_per_wall_s"] <= 1.15 for s in arm["owners"].values())):
            raise ValueError("Duplicate, mismatched or non-1x arm")
        if any(s["candidate_bound_six"] != (item["lane"] == "candidate") for s in arm["owners"].values()):
            raise ValueError("Door binding differs from the assigned arm")
        arm.update(lane=item["lane"], wasm_sha256=item["engine_sha256"])
        arms[key] = arm
    modes, lanes = ("ff-guns", "ff-sabers"), ("control", "candidate")
    if set(arms) != {(mode, lane) for mode in modes for lane in lanes}:
        raise ValueError("Four distinct arms are required")
    if (len({a["requested_shared_wall_s"] for a in arms.values()}) != 1 or
            any(arms[modes[0], lane]["wasm_sha256"] != arms[modes[1], lane]["wasm_sha256"] for lane in lanes)
            or arms[modes[0], lanes[0]]["wasm_sha256"] == arms[modes[0], lanes[1]]["wasm_sha256"]):
        raise ValueError("Room durations or engine assignments differ from the paired design")
    pairs = {}
    for mode in modes:
        pairs[mode] = {}
        for seat in STARTS:
            control, candidate = (arms[mode, lane]["owners"][seat] for lane in lanes)
            fields = ("start_sector", "start_position", "start_look", "start_health", "start_keys_83_84")
            pairs[mode][seat] = dict(
                differing_start_fields=[k for k in fields if control[k] != candidate[k]],
                nearest_weapon_bins_control_candidate=[
                    min(s["weapon_observations_around_placement"], key=lambda v: abs(v["offset_game_s"]))["weapon"]
                    for s in (control, candidate)],
                opponent_join_to_placement_control_candidate_wall_s=[
                    s["placement_after_opponent_join_wall_s"] for s in (control, candidate)])
    return dict(schema=1, fixture=fixture, pairs=pairs, measures={
        "elapsed": "Game seconds from that owner's verified placement until the first qualifying sample.",
        "first_life": "Stops at a dead observation, respawn marker, companion death count, or room deadline.",
        "chamber_clear": "A living Lily observed outside 505, its two approach sectors 509/510, and door sectors 507/506.",
        "door_passage": "Three consecutive distinct observed sectors: near side, doorway, far side. Thin sectors may be skipped.",
        "flag": "Carrying requires the enemy flag inventory bin. A shared capture requires both owner consoles' announcement.",
        "coverage": "One qualified room per engine and ruleset; weapon snapshots bracket the placement clock.",
    }, arms=list(arms.values()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    parser.add_argument("--suite", action="store_true", help="Score the four arms in a comparison directory")
    args = parser.parse_args()
    print(json.dumps((score_suite if args.suite else score_arm)(args.folder), indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
