"""Build and verify the privately staged Canyon Oasis two-start experiment."""
from hashlib import sha256
from math import dist, isfinite
from pathlib import Path
import re
import struct

from manager.content import archive_index

STOCK_GOB = "27a4b3642e0965753232f35b1e8e846c91df1eca1da77398b5efda66ca369a2e"
STOCK_MAP = "87bb3e919ee1f3749595f1ee37965bc083dbb866148775fd64280b0170926ecc"
VARIANT_GOB = "9585f8c54df1e2c5fbe2645af56e9f635dcd572e5ef6aa896d278c902699320c"
READY_GATE_GOB = "6b72d772a8a0cc61d84aff3811d4cc5b9d2039c1df055646e44bcb7131fdaab6"
VARIANT_MAP = "704f786cc494e3593dcf18815247e678dbde9f0f53e09164300b1b7d81860ad8"
COG = Path(__file__).with_name("arena_start.cog")
LEVEL = "jkl/m10.jkl"
SCRIPT = "cog/arena_start.cog"
STARTS = {1: (41, (2.399950, 0.775153, 1.120114)), 2: (18, (2.300000, 1.534940, -0.879886))}
_JOIN = re.compile(r"BOT_JOINED slot=(\d+) net=(\d+)")
_POSITION = re.compile(r"<([-0-9.]+) ([-0-9.]+) ([-0-9.]+)>")


def digest(data):
    return sha256(data).hexdigest()


def patch_level(original):
    if digest(original) != STOCK_MAP:
        raise ValueError("Unexpected Canyon Oasis level bytes")
    result = original
    newline = b"\r\n" if b"\r\n" in original else b"\n"
    for section, token, capacity, index in ((b"cogscripts", b"scripts", 30, 30), (b"cogs", b"cogs", 32, 6)):
        header = re.search(rb"(?im)^Section: " + section + rb"[ \t]*\r?$", result)
        start = header.end()
        end = start + re.search(rb"(?im)^end\b", result[start:]).start()
        body = result[start:end]
        declaration = b"World " + token + b" " + str(capacity).encode()
        if body.count(declaration) != 1 or len(re.findall(rb"(?m)^\s*\d+:", body)) != index:
            raise ValueError("Unexpected stock script table layout")
        if capacity == index:
            body = body.replace(declaration, b"World " + token + b" " + str(capacity + 1).encode())
        instance = str(index).encode() + b":\tarena_start.cog" + newline
        result = result[:start] + body + instance + result[end:]
    return result


def read_entries(archive):
    entries = {}
    with archive.open("rb") as stream:
        for item in archive_index(archive):
            stream.seek(item["offset"])
            entries[item["name"]] = stream.read(item["size"])
    return entries


def build(archive, output, *, ready_gate=False):
    """Build in a new path. The source is an exact stock GOB owned by the caller."""
    if digest(archive.read_bytes()) != STOCK_GOB:
        raise ValueError("Unexpected stock episode")
    entries = read_entries(archive)
    entries[LEVEL] = patch_level(entries[LEVEL])
    expected_gob = READY_GATE_GOB if ready_gate else VARIANT_GOB
    source = COG.with_name("arena_ready_gate.cog") if ready_gate else COG
    script = source.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
    entries[SCRIPT] = script

    payload = bytearray(b"GOB " + struct.pack("<II", 20, 0))
    index = bytearray(struct.pack("<I", len(entries)))
    for name, content in entries.items():
        raw_name = name.replace("/", "\\").encode("ascii")
        index.extend(struct.pack("<II128s", len(payload), len(content), raw_name))
        payload.extend(content)
    struct.pack_into("<I", payload, 8, len(payload))
    payload.extend(index)
    if digest(payload) != expected_gob or digest(entries[LEVEL]) != VARIANT_MAP:
        raise ValueError("Derived content differs from the qualified start fixture")
    with output.open("xb") as stream:
        stream.write(payload)
    if read_entries(output) != entries:
        raise ValueError("Private episode readback differs from generated entries")
    return {"stock_gob_sha256": STOCK_GOB, "stock_jkl_sha256": STOCK_MAP,
            "variant_gob_sha256": expected_gob, "variant_jkl_sha256": VARIANT_MAP,
            "cog_sha256": digest(script), "unchanged_entry_count": len(entries) - 2}


def observe(log, joined):
    """Match one owner log and connection in a single map to COG life and bin 9 readbacks."""
    lines = [item.strip() for item in log.read_text(encoding="ascii", errors="replace").splitlines()
             if item.strip()]
    joins = [match.groups() for line in lines if (match := _JOIN.fullmatch(line))]
    loads = [line.removeprefix("OpenJKDF2: sithWorld_Load -> ") for line in lines
             if line.startswith("OpenJKDF2: sithWorld_Load -> ")]
    if joins != [(str(joined["slot"]), str(joined["net"]))] or joined["slot"] not in STARTS:
        raise ValueError("Missing or ambiguous seat identity")
    if loads.count("m10.jkl") != 1 or loads[-1] != "m10.jkl":
        raise ValueError("Missing or ambiguous Canyon Oasis world")
    map_line = lines.index("OpenJKDF2: sithWorld_Load -> m10.jkl")
    join_line = lines.index(f"BOT_JOINED slot={joined['slot']} net={joined['net']}")
    if join_line <= map_line:
        raise ValueError("Joined before the measured world loaded")
    events = []
    life = 0
    previous = None
    last_time = -1.0
    next_base = False
    for i, line in enumerate(lines):
        if not line.startswith("ADJOIN_"):
            continue
        if i <= join_line:
            raise ValueError("Fixture evidence precedes the observed join")
        if line in ("ADJOIN_OPENING", "ADJOIN_RESPAWN"):
            first = line == "ADJOIN_OPENING"
            if first != (life == 0) or next_base:
                raise ValueError("Unexpected life boundary or missing inventory baseline")
            slot = int(lines[i+1])
            sector = int(lines[i+2])
            match = _POSITION.fullmatch(lines[i+3])
            if slot != joined["slot"] or not match or sector < 0:
                raise ValueError("Invalid reported seat or position")
            position = tuple(map(float, match.groups()))
            if not all(isfinite(x) for x in position):
                raise ValueError("Nonfinite player position")
            life += 1
            next_base = True
            event = dict(kind="opening" if first else "respawn", life_ordinal=life,
                         sector=sector, position=list(position), mask_readback=int(lines[i+4+int(first)]))
            if first:
                expected_sector, expected_position = STARTS[slot]
                event["mask_before"] = int(lines[i+4])
                if (sector != expected_sector or dist(position, expected_position) > 0.000002
                        or event["mask_before"] != 0 or event["mask_readback"] != event["mask_before"]):
                    raise ValueError("Opening disagrees with the authored pose or stock mask")
            elif event["mask_readback"] != 0:
                raise ValueError("Ordinary respawn mask changed")
        elif line == "ADJOIN_RIFLE_BASE":
            if not next_base:
                raise ValueError("Inventory baseline without matching life boundary")
            previous = int(lines[i+1])
            if previous not in (0, 1) or (life == 1 and previous != 0):
                raise ValueError("Invalid initial rifle inventory")
            event = dict(kind="life_initial_inventory", life_ordinal=life, bin=9, amount=previous)
            next_base = False
        elif line == "ADJOIN_RIFLE_CHANGE":
            old, new = int(lines[i+1]), int(lines[i+2])
            when = float(lines[i+3])
            if (next_base or previous != old or old == new or new not in (0, 1)
                    or not isfinite(when) or when < 0 or when < last_time):
                raise ValueError("Inventory transition inconsistent with owner history")
            last_time, previous = when, new
            event = dict(kind="sampled_inventory_change", life_ordinal=life, bin=9,
                         previous=old, current=new, level_time_s=when)
        else:
            raise ValueError("Unknown fixture message")
        events.append(event)
    respawns = sum(line.startswith("BOT_RESPAWN ") for line in lines[join_line+1:])
    if life != respawns + 1:
        raise ValueError("Owner life boundaries disagree with native respawn notices")
    if not life or next_base:
        raise ValueError("Incomplete opening or inventory baseline")
    return {"slot": joined["slot"], "net": joined["net"], "events": events,
            "log_sha256": digest(log.read_bytes())}


def qualify(directory, bots):
    measured = {side: observe(directory / (side + ".log"), bots[side]["joined"])
                for side in ("dark", "light")}
    if {row["slot"] for row in measured.values()} != {1, 2} or len({row["net"] for row in measured.values()}) != 2:
        raise ValueError("Two distinct joined owners required")
    return measured
