"""Prepare a private JHS navigation drill by relocating only the six player starts."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct

from manager.content import archive_index
from web_gateway.assets import pack_files
from .map_coverage import JHS_GOB, JHS_MAP, ROOT, run_cell

# Each spawn is on a flat, solid authored landing with a player-height offset.
# 124 has rail charges and 121 has stormtrooper rifles. Both are below sector 58.
STARTS = {
    10: "4.48 -3.55 1.372 0 90 0 124",
    31: "3.090 -3.55 2.485 0 0 0 121",
    180: "4.60 -3.68 1.372 0 90 0 124",
    235: "3.190 -3.67 2.485 0 0 0 121",
    238: "4.49 -3.69 1.372 0 90 0 124",
    260: "3.197 -3.53 2.485 0 0 0 121",
}
LIFT_STARTS = {
    index: f"{x:.3f} -3.02 2.815 0 -90 0 79"
    for index, x in zip((10, 31, 180, 235, 238, 260), (.27, .10, -.07, -.24, -.41, -.58))
}
DECK_STARTS = {
    index: f"{x:.3f} {y:.3f} 2.855 0 90 0 30"
    for index, (x, y) in zip(STARTS, ((.459, -3.075), (.575, -2.972), (.46, -2.972),
                                      (.57, -3.075), (.513, -3.02), (.511, -3.085)))
}
GRATE_STARTS = {
    index: f"{x:.3f} {y:.3f} 2.815 0 -90 0 79"
    for index, (x, y) in zip(STARTS, ((.294, -2.99), (.294, -3.06), (.294, -3.02),
                                      (.28, -3.04), (.28, -2.977), (.28, -3.08)))
}
OPENINGS = {"chute": STARTS, "middle-lift": LIFT_STARTS, "lift-deck": DECK_STARTS, "hall-grate": GRATE_STARTS}


def prepare(original, output, start_area="chute", grate_sensor=None):
    def digest(data):
        return hashlib.sha256(data).hexdigest()

    if output.resolve().is_relative_to(ROOT):
        raise ValueError("Keep the private practice episode outside the repository")
    source = original.read_bytes()
    if digest(source) != JHS_GOB:
        raise ValueError("The original JHS GOB is required")
    if start_area not in (*OPENINGS, "nearest-original", "entrance-original"):
        raise ValueError("Unknown practice opening")
    entries = archive_index(original)
    contents = {e["name"]: source[e["offset"]:e["offset"] + e["size"]] for e in entries}
    key, = [k for k in contents if k.casefold() == "jkl/jhs.jkl"]
    if digest(contents[key]) != JHS_MAP:
        raise ValueError("JHS JKL digest mismatch")
    if start_area in ("nearest-original", "entrance-original"):
        starts = {int(r[1]): r[2].decode("ascii") for r in re.finditer(
            rb"(?m)^(\d+): walkplayer walkplayer ([^\r\n]+)", contents[key])}
        # The engine's first solo host consistently chose slot four in the tested build.
        # Swap two original starts to exercise 135 without inventing a seventh position.
        origin = 235 if start_area == "nearest-original" else 31
        starts[origin], starts[238] = starts[238], starts[origin]
    else:
        starts = OPENINGS[start_area]
    seen = set()

    def relocate(match):
        index = int(match[1])
        if index in seen or index not in starts:
            raise ValueError("Unexpected walkplayer entry")
        seen.add(index)
        return match[1] + b": walkplayer walkplayer " + starts[index].encode("ascii")

    contents[key] = re.sub(rb"(?m)^(\d+): walkplayer walkplayer [^\r\n]+", relocate, contents[key])
    if seen != set(starts):
        raise ValueError("Missing original start")
    if grate_sensor:
        if start_area != "hall-grate":
            raise ValueError("Use the grate sensor only with the hall-grate opening")
        from .analysis.jhs_route_geometry import resource
        name = "cog/00_slashgrate.cog"
        stock = resource(grate_sensor, name)
        if digest(stock) != "9b737dee56d44dff90626a865fcee9db0da241cb1c617b48735dffd6dc8e71d9":
            raise ValueError("Expected the original stock grate COG")
        code = stock.decode("latin1").replace("\r", "")
        code = code.replace("message\tdamaged", "message damaged\nmessage startup\nmessage pulse\nint watch=91 local")
        code = code.replace("damaged:", "startup:\n  if (grate != 868) return;\n  SetPulse(0.5);\n  return;\n"
                            "pulse:\n  SetInv(jkGetLocalPlayer(),60,watch);\n  return;\ndamaged:\n   watch=77;")
        code = code.replace("setadjoinflags(grateback,2);", "setadjoinflags(grateback,2);\n      watch=43;")
        contents[name] = code.replace("\n", "\r\n").encode("latin1")
    packed, _ = pack_files(contents.items())
    # JK's native GOB loader looks up DOS path separators. Preserve the original
    # raw entry names, including case and padding, while using the new offsets.
    episode = bytearray(packed)
    source_index = struct.unpack_from("<I", source, 8)[0]
    dest_index = struct.unpack_from("<I", episode, 8)[0]
    for i in range(len(entries)):
        old = source_index + 12 + 136 * i
        new = dest_index + 12 + 136 * i
        episode[new:new + 128] = source[old:old + 128]
    if grate_sensor:
        for i, name in enumerate(contents):
            offset = dest_index + 12 + 136 * i
            episode[offset:offset + 128] = name.replace("/", "\\").encode("ascii").ljust(128, b"\0")
    output.mkdir(parents=True, exist_ok=False)
    target = output / "jhs_upper.gob"
    target.write_bytes(episode)
    for entry in archive_index(target):
        payload = episode[entry["offset"]:entry["offset"] + entry["size"]]
        if payload != contents[entry["name"]]:
            raise ValueError("Practice GOB failed read-back verification")
    manifest = dict(episode_sha256=digest(episode), map_sha256=digest(contents[key]), original_map_sha256=JHS_MAP,
                    original_episode_sha256=JHS_GOB, changed_starts=starts, opening=start_area,
                    target_sectors=[57, 58] if start_area == "chute" else [0], grate_sensor=bool(grate_sensor),
                    label="Relocated starts. Original-map matches are scored separately.")
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("episode", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--start-area", choices=(*OPENINGS, "nearest-original", "entrance-original"), default="chute")
    parser.add_argument("--grate-sensor", type=Path, metavar="RES2_GOB",
                        help="Private solo diagnostic. Report grate 868's COG state in the player's shields.")
    parser.add_argument("--run", action="store_true", help="Run a native NF guns match once the new fixture is ready.")
    parser.add_argument("--repo", type=Path, default=ROOT)
    parser.add_argument("--data", type=Path)
    parser.add_argument("--pace-build", type=Path)
    clients = parser.add_mutually_exclusive_group()
    clients.add_argument("--stock-build", type=Path, help="A competitive build admitting local custom episodes.")
    clients.add_argument("--platform-build", type=Path, help="Prior native client with verified custom admission.")
    parser.add_argument("--jan-first", action="store_true")
    parser.add_argument("--seconds", type=int, choices=range(15, 121), metavar="15..120", default=60)
    a = parser.parse_args()
    if a.run and not (a.data and a.pace_build and (a.stock_build or a.platform_build)):
        parser.error("--run requires --data, --pace-build and one client build")
    fixture = prepare(a.episode, a.output, a.start_area, a.grate_sensor)
    print(json.dumps(fixture), flush=True)
    if a.run:
        a.jhs_client = "platform" if a.platform_build else "competitive"
        a.jhs_gob = a.output / "jhs_upper.gob"
        a.rate, a.brain_trace = 1, False
        cell = dict(key=a.start_area, episode="jhs", map="jhs.jkl", mode="ffa", weapons="guns", force="off",
                    episode_sha256=fixture["episode_sha256"], map_sha256=fixture["map_sha256"])
        raise SystemExit(0 if run_cell(a, cell) else 1)
