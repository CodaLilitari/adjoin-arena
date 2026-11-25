"""Check the authored JHS entrance annotation against a local JKL and stock 3DO faces."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re

from manager.content import archive_index
from .native_duel import require


def resource(archive, name):
    item, = [e for e in archive_index(archive) if e["name"].lower() == name]
    with archive.open("rb") as stream:
        stream.seek(item["offset"])
        return stream.read(item["size"])


def numbered(lines, heading, number=None):
    start = next(i for i,s in enumerate(lines) if s.strip().casefold() == heading.casefold()
                 or s.casefold().startswith(heading.casefold() + " "))
    if number is None:
        number = int(lines[start].split()[-1])
    rows = []
    for line in lines[start+1:]:
        m = re.match(r"\s*(\d+):\s*(.*)", line)
        if m:
            require(int(m[1]) == len(rows), heading + " row order")
            rows.append(m[2])
            if len(rows) == number:
                return rows
    raise ValueError(heading + " truncated")


def point(row):
    return tuple(map(float, row.split()[:3]))


def face_vertices(row, vertices):
    return [vertices[int(n)] for n in re.findall(r"(\d+)\s*,\s*\d+", row)]


def footprint(poly, x, y):
    inside = False
    for a,b in zip(poly, poly[1:] + poly[:1]):
        if (a[1] > y) != (b[1] > y) and x < a[0] + (y-a[1])*(b[0]-a[0])/(b[1]-a[1]):
            inside = not inside
    return inside


def top_faces(model, origin):
    lines = model.decode("latin1").splitlines()
    vertices = [tuple(a+b for a,b in zip(point(row),origin)) for row in numbered(lines,"VERTICES")]
    faces = numbered(lines,"FACES")
    normals = [point(row) for row in numbered(lines,"FACE NORMALS",len(faces))]
    return [face_vertices(row,vertices) for row,n in zip(faces,normals) if n[2] > .95]


def audit(episode, stock, route):
    data = resource(episode,"jkl/jhs.jkl")
    lines = data.decode("latin1").splitlines()
    raw = route.read_bytes()
    header,*rows = raw.decode("ascii").splitlines()
    magic,digest,count = header.split()
    require(magic == "RED_ROUTE_HINT_V1" and digest == hashlib.sha256(data).hexdigest()
            and int(count) == len(rows), "Route identity")
    hints = [tuple(map(int,row.split())) for row in rows]
    vertices = [point(row) for row in numbered(lines,"World vertices")]
    surfaces = numbered(lines,"World surfaces")
    normal = [point(row) for row in numbered(lines,"#--- Surface normals ---", len(surfaces))]
    fixture_ids = (184,183,182,181)
    things = numbered(lines,"World things",max(fixture_ids)+1)
    meshes = {"landpad":"landpad.3do","3x10catwalk":"c3x10.3do"}
    floors, provenance = {}, {}
    for fixture in fixture_ids:
        obj = things[fixture].split()
        require(obj[8] == "5" and all(float(k)==0 for k in obj[5:8]), "Unexpected fixture transform")
        meshname = meshes[obj[0]]
        model = resource(stock,"3do/"+meshname)
        origin = tuple(map(float,obj[2:5]))
        floors[fixture] = top_faces(model,origin)
        provenance[str(fixture)] = {"model":meshname,"model_sha256":hashlib.sha256(model).hexdigest(),
                                    "origin":origin}
    section = lines.index("SECTOR 7")
    start,count = map(int,next(row for row in lines[section:] if row.startswith("SURFACES ")).split()[1:])
    floors[-1] = [face_vertices(surfaces[i],vertices) for i in range(start,start+count)
                  if normal[i][2]>.95 and surfaces[i].split()[6] == "-1"]
    portal = face_vertices(surfaces[74],vertices)
    adj = numbered(lines,"World adjoins")
    adjoin = int(surfaces[74].split()[6])
    flags,mirror,_ = adj[adjoin].split()
    require(int(flags,16)&2 and any(int(s.split()[6])==int(mirror) for s in surfaces[start:start+count]),
            "Missing passable portal to sector 7")
    require(all(abs(v[1]+9.105)<0.00001 for v in portal), "Unexpected portal plane")
    for sector,fixture,x,y,z in hints:
        require(sector==(7 if fixture==-1 else 5) and any(footprint(poly,x/1000,y/1000)
                and abs(z/1000 - poly[0][2] - .12)<.040 for poly in floors[fixture]),
                f"Waypoint {x},{y} not on expected support {fixture}")
    probes = 0
    all_polys = sum(floors.values(), [])
    for a,b in zip(hints,hints[1:]):
        x0,y0 = a[2]/1000,a[3]/1000
        dx,dy = (b[2]-a[2])/1000,(b[3]-a[3])/1000
        length = math.hypot(dx,dy)
        steps = math.ceil(length/.005)
        for n in range(steps+1):
            for offset in (-.04,0,.04):
                x = x0+dx*n/steps-offset*dy/length
                y = y0+dy*n/steps+offset*dx/length
                require(any(footprint(poly,x,y) for poly in all_polys), f"Unsupported corridor sample {x},{y}")
                probes += 1
    return {"schema":1,"map_sha256":digest,"route_sha256":hashlib.sha256(raw).hexdigest(),
            "fixtures":provenance,"exit_portal_surface":74,"exit_sector":7,
            "waypoints":len(hints),"support_samples":probes,"maximum_sample_spacing":.005,
            "side_offsets":[-.04,0,.04],"interpretation":"Static projected support check. The native client checks height, support, walls and movement in the live world."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("episode","stock","route","output"):
        parser.add_argument("--"+name, required=True, type=Path)
    args = parser.parse_args()
    result = audit(args.episode,args.stock,args.route)
    with args.output.open("x",encoding="utf-8",newline="\n") as stream:
        json.dump(result,stream,indent=2)
        stream.write("\n")
