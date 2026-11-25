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
SWAPPED_GATE_GOB = "9e6213e9c826f42648223f198e93c1c683af56de7a8095facce148de5058a9fc"
REPEATER_GATE_GOBS = {False: "b791a52ba1892f38ad98927ac8d5f0806b75b78153f8ebee124b24ef4a7de748", True: "0c2e6d1756107e9b7b229857bfbf8af8db955341a1b41c5d0c88f041ea972fde"}
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


def replace_once(script, before, after):
    if script.count(before) != 1:
        raise ValueError("Unexpected ready-gate script layout")
    return script.replace(before, after)


def opening_script(ready_gate, swap_starts, observe_repeater):
    if (swap_starts or observe_repeater) and not ready_gate:
        raise ValueError("Swapping starts or observing the repeater requires the ready gate")
    source = COG.with_name("arena_ready_gate.cog") if ready_gate else COG
    script = source.read_text(encoding="ascii")
    if swap_starts:
        script = replace_once(
            script,
            "if (slot == 1) SetRespawnMask(player, 0xFFFFFFFD);\n   else SetRespawnMask(player, 0xFFFFFBFF);",
            "if (slot == 1) SetRespawnMask(player, 0xFFFFFBFF);\n   else SetRespawnMask(player, 0xFFFFFFFD);")
    if observe_repeater:
        script = replace_once(script, "int rifle=-1", "int repeater=-1 local\nint rifle=-1")
        script = replace_once(script, "   PrintInt(rifle);\n   return;\n\npulse:", """   PrintInt(rifle);
   repeater = GetInv(player, 6);
   Print("ARENA_REPEATER_BASE");
   PrintInt(slot);
   PrintInt(repeater);
   PrintFlex(GetLevelTime());
   return;

pulse:""")
        script = replace_once(script, "   return;\ntrigger:", """   if (((slot == 1) || (slot == 2)) && (repeater >= 0))
   {
      sample = GetInv(player, 6);
      if (sample != repeater)
      {
         Print("ARENA_REPEATER_CHANGE");
         PrintInt(slot);
         PrintInt(repeater);
         PrintInt(sample);
         PrintFlex(GetLevelTime());
         repeater = sample;
      }
   }
   return;
trigger:""")
    return script.replace("\n", "\r\n").encode("ascii")


def build(archive, output, *, ready_gate=False, swap_starts=False, observe_repeater=False):
    """Build one pinned scenario in a new path using an owned stock episode."""
    script = opening_script(ready_gate, swap_starts, observe_repeater)
    if digest(archive.read_bytes()) != STOCK_GOB:
        raise ValueError("Unexpected stock episode")
    entries = read_entries(archive)
    entries[LEVEL] = patch_level(entries[LEVEL])
    expected_gob = READY_GATE_GOB if ready_gate else VARIANT_GOB
    if swap_starts:
        expected_gob = SWAPPED_GATE_GOB
    if observe_repeater:
        expected_gob = REPEATER_GATE_GOBS[swap_starts]
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
    return {"start_assignment": "swapped" if swap_starts else "normal", "observe_repeater": observe_repeater,
            "stock_gob_sha256": STOCK_GOB, "stock_jkl_sha256": STOCK_MAP,
            "variant_gob_sha256": expected_gob, "variant_jkl_sha256": VARIANT_MAP,
            "cog_sha256": digest(script), "unchanged_entry_count": len(entries) - 2}


def observe(log, joined, *, swap_starts=False):
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
                expected_sector, expected_position = STARTS[3 - slot if swap_starts else slot]
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


def qualify(directory, bots, *, swap_starts=False):
    measured = {side: observe(directory / (side + ".log"), bots[side]["joined"], swap_starts=swap_starts)
                for side in ("dark", "light")}
    if swap_starts and (measured["dark"]["slot"], measured["light"]["slot"]) != (1, 2):
        raise ValueError("Swapping starts must preserve the original owners and join order")
    if {row["slot"] for row in measured.values()} != {1, 2} or len({row["net"] for row in measured.values()}) != 2:
        raise ValueError("Two distinct joined owners required")
    return measured


def qualify_repeater(directory, openings, gate):
    """Bind bin 6 samples to the same owning clients, life boundaries and local release clocks."""
    measured = {}
    for side, slot in (("dark", 1), ("light", 2)):
        opening = openings[side]
        owner = gate["owners"][side]
        raw = (directory / (side + ".log")).read_bytes()
        if (digest(raw) != opening["log_sha256"] or opening["slot"] != slot
                or (owner["slot"], owner["net"]) != (slot, opening["net"])):
            raise ValueError("Repeater sample owner does not match gate and opening")
        lines = [s.strip() for s in raw.decode("ascii", errors="replace").splitlines() if s.strip()]
        unlock = lines.index("GATE_UNLOCK_APPLIED")
        expected_lives = [e["life_ordinal"] for e in opening["events"] if e["kind"] == "life_initial_inventory"]
        events = []
        life = 0
        previous = None
        last_time = -1.0
        for i, marker in enumerate(lines):
            if marker in ("ADJOIN_OPENING", "ADJOIN_RESPAWN"):
                if life and previous is None:
                    raise ValueError("Missing repeater baseline before respawn")
                life += 1
                previous = None
                continue
            if not marker.startswith("ARENA_REPEATER_"):
                continue
            if not life or int(lines[i+1]) != slot:
                raise ValueError("Invalid repeater seat or life")
            if marker == "ARENA_REPEATER_BASE":
                amount = int(lines[i+2])
                when = float(lines[i+3])
                if (previous is not None or i < 2 or lines[i-2] != "ADJOIN_RIFLE_BASE"
                        or amount not in (0, 1) or (life == 1 and (i >= unlock or amount != 0))
                        or (life > 1 and i <= unlock)):
                    raise ValueError("Invalid owner repeater baseline")
                event = dict(kind="life_initial_inventory", life_ordinal=life, amount=amount, level_time_s=when)
                previous = amount
            elif marker == "ARENA_REPEATER_CHANGE":
                old, new, when = int(lines[i+2]), int(lines[i+3]), float(lines[i+4])
                if (old != previous or new not in (0, 1) or old == new or i <= unlock
                        or when < owner["unlock_time_s"]):
                    raise ValueError("Invalid or pre-release owner repeater transition")
                event = dict(kind="sampled_inventory_change", life_ordinal=life, previous=old, current=new,
                             level_time_s=when, seconds_after_release=round(when - owner["release_time_s"], 6))
                previous = new
            else:
                raise ValueError("Unknown repeater marker")
            if not isfinite(when) or when < 0 or when < last_time:
                raise ValueError("Invalid repeater owner clock")
            if life == 1 and marker == "ARENA_REPEATER_BASE" and when > owner["release_time_s"]:
                raise ValueError("Opening repeater sample clock after release")
            last_time = when
            events.append(event)
        lives = [ev["life_ordinal"] for ev in events if ev["kind"] == "life_initial_inventory"]
        if not lives or lives != expected_lives or previous is None:
            raise ValueError("Missing repeater life baseline")
        first = next((ev["seconds_after_release"] for ev in events
                      if ev["kind"] == "sampled_inventory_change" and ev["life_ordinal"] == 1
                      and ev["current"] == 1), None)
        measured[side] = dict(slot=slot, net=opening["net"], bin=6, log_sha256=opening["log_sha256"],
                              events=events, first_life_gain_after_release_s=first)
    return measured
