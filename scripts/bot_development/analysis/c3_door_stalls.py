"""Correlate first-leg stalls in a private C3 owner console with the stock door bindings."""
import argparse
from collections import Counter
from hashlib import sha256
import json
import math
from pathlib import Path
import re

from .jhs_route_geometry import numbered, resource


MAP_SHA = "b4d804591cebebbd59f05ad42a8e059178dc468e24172bd6bc5b7d6ba1c2f0a7"
EPISODE_SHA = "da98fe3fc769168f1bb562cc1f6532560b12d8e920fd6c34586d69b424b5b1fc"
DOOR_SCRIPTS = ("c3_sascolored.cog", "ctf_doorred.cog", "ctf_doorgold.cog")
FIELDS = "t sector pos health weapon target goal path deaths next edge following".split()


def level_doors(episode):
    if sha256(episode.read_bytes()).hexdigest() != EPISODE_SHA:
        raise ValueError("The original stock JK1CTF episode is required")
    raw = resource(episode, "jkl/c3.jkl")
    if sha256(raw).hexdigest() != MAP_SHA:
        raise ValueError("Stock C3 JKL required")
    text = raw.decode("latin1")
    lines = text.splitlines()
    surfaces = numbered(lines, "World surfaces")
    adjoins = numbered(lines, "World adjoins")
    owners = {}
    sector = None
    for line in lines:
        if line.startswith("SECTOR\t"):
            sector = int(line.split()[1])
        if sector is None or not line.startswith("SURFACES\t"):
            continue
        first, count = map(int, line.split()[1:3])
        for side in range(first, first + count):
            adjoin = int(surfaces[side].split()[6])
            if adjoin >= 0:
                owners[adjoin] = sector
        sector = None
    adjacent = {}
    for i, sector in owners.items():
        flags, mirror, _ = adjoins[i].split()
        if int(flags, 16) & 2:
            adjacent.setdefault(sector, set()).add(owners[int(mirror)])

    # The JKL loader stops at 'end'; the World things capacity exceeds the placed count.
    def entries(section):
        start = next(i for i, line in enumerate(lines) if line.casefold().startswith(section + " "))
        for line in lines[start + 1:]:
            if line.strip().casefold() == "end":
                break
            match = re.match(r"\s*(\d+):\s*(\S.*)", line)
            if match:
                yield int(match[1]), match[2].lower().split()

    things = dict(entries("world things"))
    door_data = {}
    for instance, row in entries("world cogs"):
        name = row[0]
        if name not in DOOR_SCRIPTS:
            continue
        if name == "c3_sascolored.cog":
            bindings = [(int(row[1]), "interior", 82 + int(row[4])),
                        (int(row[2]), "exterior", None)]
        else:
            bindings = [(int(row[1]), "single", 83 if name == "ctf_doorred.cog" else 84)]
        for thing, role, key in bindings:
            entry = things[thing]
            door_data[thing] = dict(thing=thing, sector=int(entry[8]), instance=instance, script=name,
                                    role=role, key_bin=key, position=tuple(map(float, entry[2:5])))
    return adjacent, door_data


def read_owner(path):
    raw = path.read_bytes()
    notices = Counter()
    status = []
    owner = None
    team = None
    c3 = False
    for line in raw.decode("utf-8", errors="replace").splitlines():
        if "BOT_NAV nodes=" in line and "map=c3.jkl " in line:
            c3 = True
        if match := re.search(r"\blog You need the (Red|Gold) key\.\.\.\s*$", line, re.I):
            notices[match[1].lower()] += 1
        if match := re.search(r"BOT_OBJECTIVE\b.*\bteam=(\d+)\b", line):
            team = int(match[1])
        if "BOT_STATUS " in line:
            fields = dict(re.findall(r"(\w+)=([^\s]+)", line.split("BOT_STATUS ", 1)[1]))
            if owner is not None and fields["name"] != owner:
                raise ValueError("A single owner console is required")
            owner = fields["name"]
            status.append([team, *(fields[key] for key in FIELDS)])
    if not (c3 and status):
        raise ValueError("Expected C3 owner status in " + path.name)
    return dict(owner=owner, source_sha256=sha256(raw).hexdigest(), key_denials=dict(notices), samples=status)


def analyze(owner, adjacent, doors):
    groups, window = [], []
    weapons = set()
    for side, *values in owner["samples"]:
        fields = dict(zip(FIELDS, values, strict=True))
        weapons.add(int(fields["weapon"]))
        xyzt = tuple(map(float, fields["pos"].split(","))) + (float(fields["t"]),)
        signature = (int(fields["sector"]), int(fields["next"]), side, fields["deaths"])
        live = (int(fields["following"]) and fields["target"] == "-1" and fields["edge"] == "0"
                and fields["path"].startswith("0/") and float(fields["health"]) > 0 and side in (1, 2))
        if window and (not live or signature != window[0][0] or not 0 < xyzt[3] - window[-1][1][3] <= 11
                       or math.dist(xyzt[:2], window[0][1][:2]) > .03):
            groups.append(window)
            window = []
        if live:
            window.append((signature, xyzt, int(fields["goal"])))
    groups.append(window)
    stalls = []
    for group in groups:
        if len(group) < 4 or group[-1][1][3] - group[0][1][3] < 29:
            continue
        (sector, node, team, _), first, _ = group[0]
        neighbors = adjacent.get(sector, set())
        positions = [row[1] for row in group]
        nearby = []
        for door in doors.values():
            via = sorted(s for s in neighbors if door["sector"] in adjacent.get(s, set()))
            dx = math.dist(first[:2], door["position"][:2])
            if (door["sector"] in neighbors or via) and dx <= .65:
                nearby.append({k: v for k, v in door.items() if k != "position"} |
                              dict(horizontal_distance=round(dx, 3), via_sectors=via))
        stalls.append(dict(sector=sector, next_node=node, team=team, samples=len(group),
                           game_seconds=[first[3], positions[-1][3]], reference_xy=first[:2],
                           max_xy_drift=round(max(math.dist(first[:2], p[:2]) for p in positions), 3),
                           vertical_range=[min(p[2] for p in positions), max(p[2] for p in positions)],
                           distinct_route_goals=len({row[2] for row in group}),
                           nearby_doors=sorted(nearby, key=lambda d: d["horizontal_distance"])))
    return dict(owner=owner["owner"], status_weapon_bins=sorted(weapons),
                source_sha256=owner["source_sha256"],
                owner_session_key_denials=owner["key_denials"], sustained_stalls=stalls)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("episode", type=Path)
    parser.add_argument("owner_logs", nargs="*", type=Path)
    parser.add_argument("--replay", type=Path, help="Score the shareable owner samples instead of live logs")
    parser.add_argument("--save-replay", type=Path, help="Save only the scoring fields from the supplied logs")
    args = parser.parse_args()
    if bool(args.owner_logs) == bool(args.replay) or args.save_replay and args.replay:
        parser.error("Supply owner console logs or one --replay")
    graph, doors = level_doors(args.episode)
    columns = ["team", *FIELDS]
    if args.replay:
        replay = json.loads(args.replay.read_bytes())
        if replay["map_sha256"] != MAP_SHA or replay["columns"] != columns:
            raise ValueError("Replay map or sample columns do not match stock C3")
        owners = replay["owners"]
    else:
        owners = [read_owner(path) for path in args.owner_logs]
        if args.save_replay:
            replay = dict(map_sha256=MAP_SHA, columns=columns, owners=owners)
            with args.save_replay.open("x", encoding="utf-8", newline="\n") as output:
                json.dump(replay, output, separators=(",", ":"))
                output.write("\n")
    result = dict(episode_sha256=EPISODE_SHA, map_sha256=MAP_SHA,
                  script_sha256={n: sha256(resource(args.episode, "cog/" + n)).hexdigest()
                                 for n in DOOR_SCRIPTS},
                  criterion="At least four consecutive living/status samples spanning 29 game seconds on the same first walk leg, with the same team and death count, no combat target, and horizontal drift within 0.03 units of the first sample.",
                  owners=[analyze(owner, graph, doors) for owner in owners])
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
