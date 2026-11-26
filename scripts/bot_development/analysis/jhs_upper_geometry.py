"""Check JHS floor regions, upper-ramp portals and the final railgun lip in the owner's episode."""
import argparse
import hashlib
import json
from pathlib import Path
import re

from .jhs_route_geometry import face_vertices, numbered, point, resource
from ..map_coverage import JHS_GOB, JHS_MAP
from ..score_map_coverage import JHS_ASCENT, JHS_REGIONS


def audit(episode, stock=None):
    if hashlib.sha256(episode.read_bytes()).hexdigest() != JHS_GOB:
        raise ValueError("Original JHS archive required")
    raw = resource(episode, "jkl/jhs.jkl")
    if hashlib.sha256(raw).hexdigest() != JHS_MAP:
        raise ValueError("JHS level digest mismatch")
    text = raw.decode("latin1")
    lines = text.splitlines()
    vertices = [point(row) for row in numbered(lines, "World vertices")]
    surfaces = numbered(lines, "World surfaces")
    normals = [point(row) for row in numbered(lines, "#--- Surface normals ---", len(surfaces))]
    adjoins = numbered(lines, "World adjoins")
    owners, floors, links = {}, {}, {}
    for index, body in re.findall(r"(?ms)^SECTOR (\d+)\s*\n(.*?)(?=^SECTOR \d+\s*$|^end\s*$)", text):
        sector = int(index)
        first, count = map(int, re.search(r"(?m)^SURFACES (\d+) (\d+)", body).groups())
        floors[sector] = []
        for side in range(first, first + count):
            adj = int(surfaces[side].split()[6])
            if adj >= 0:
                owners[adj] = sector
                links[adj] = side
            elif normals[side][2] > .55:
                floors[sector].extend(p[2] for p in face_vertices(surfaces[side], vertices))
    edges = {(sector, owners[int(adjoins[adj].split()[1])]): links[adj] for adj, sector in owners.items()}
    route = []
    for source, dest in zip(JHS_ASCENT, JHS_ASCENT[1:]):
        face = edges[source, dest]
        adj = int(surfaces[face].split()[6])
        # Original JHS uses the stock render/move/sound portal flags throughout this ascent.
        flags = int(adjoins[adj].split()[0], 16)
        if flags != 7:
            raise ValueError("Unexpected upper route portal flags")
        route.append(dict(source=source, destination=dest, portal=face, flags=flags,
                          opening_z=sorted({v[2] for v in face_vertices(surfaces[face], vertices)})))
    lip = min(floors[58]) - max(floors[119])
    if abs(lip - .13) > 1e-5:
        raise ValueError("Unexpected upper-passage lip height")
    slopes = [
        {"sector": sector, "surface": face, "normal_z": normals[face][2],
         "floor_flag": bool(int(surfaces[face].split()[1], 16) & 1)}
        for sector, face in ((122, 1321), (120, 1306), (119, 1299))
    ]
    if any(row["floor_flag"] for row in slopes):
        raise ValueError("Unexpected eastern chute surface flags")
    regions = {}
    for name, sectors in JHS_REGIONS.items():
        regions[name] = {"sectors": sorted(sectors), "minimum_floor_z": min(min(floors[s]) for s in sectors)}
    rows = numbered(lines, "World things", 85)
    cogs = numbered(lines, "World cogs", 32)
    if cogs[0].lower().split() != ["00_slashgrate.cog", "868", "327"]:
        raise ValueError("Unexpected middle-hall grate binding")
    grate = dict(script="00_slashgrate.cog", cog=0, front=868, reverse=327,
                 hall_to_shaft_allows_movement=bool(int(adjoins[int(surfaces[868].split()[6])].split()[0], 16) & 2))
    if stock:
        code = resource(stock, "cog/00_slashgrate.cog")
        grate["script_sha256"] = hashlib.sha256(code).hexdigest()
        if grate["script_sha256"] != "9b737dee56d44dff90626a865fcee9db0da241cb1c617b48735dffd6dc8e71d9":
            raise ValueError("Unexpected stock grate script")
        grate["opens_on_damage_types"] = [4, 16]
    lifts = []
    for thing, cog, ports in ((9, 30, ((5, 7), (7, 3), (3, 9), (9, 16), (16, 19), (19, 0))),
                              (65, 24, ((76, 78), (78, 81), (81, 79))),
                              (11, 31, ((79, 30), (30, 31), (31, 0)))):
        obj = rows[thing].split()
        script = cogs[cog].split()
        frames = [list(map(float, xyz.split("/"))) for xyz in re.findall(r"\bframe=\(([^:]+):", rows[thing])]
        if len(frames) != 2 or script[5 if thing == 65 else 1] != str(thing):
            raise ValueError("JHS lift binding differs from the authored instance")
        openings = []
        for source, dest in ports:
            face = edges[source, dest]
            adj = int(surfaces[face].split()[6])
            flags = int(adjoins[adj].split()[0], 16)
            openings.append(dict(source=source, destination=dest, portal=face, flags=flags, allows_movement=bool(flags & 2),
                                 opening_z=sorted({p[2] for p in face_vertices(surfaces[face], vertices)})))
        lifts.append(dict(thing=thing, template=obj[0], script=script[0], frames=frames, portals=openings))
    anchors = {}
    for index in (7, 24, 59, 60, 75, 76, 77):
        data = rows[index].split()
        anchors[index] = dict(template=data[0], sector=int(data[8]), position=list(map(float, data[2:5])))
    return {"episode_sha256": JHS_GOB, "map_sha256": JHS_MAP, "regions": regions, "eastern_portals": route,
            "chute_slopes": slopes, "last_lip_game_units": round(lip, 5), "authored_landmarks": anchors,
            "entrance_transporter": lifts[0], "interior_lifts": lifts[1:], "middle_grate": grate}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("episode", type=Path)
    p.add_argument("--stock", type=Path, help="Optional local Res2.gob for the grate damage handler")
    args = p.parse_args()
    print(json.dumps(audit(args.episode, args.stock), indent=2))
