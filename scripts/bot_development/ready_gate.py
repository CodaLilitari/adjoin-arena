"""Qualify the seat-coordinated Canyon Oasis opening from three native logs."""
from collections import defaultdict
from hashlib import sha256
from math import isfinite
from typing import NamedTuple
import re


# A protocol record is one COG print marker followed by a fixed number of values.
# Vectors are a single printed value. Numbers in these logs are local level time
# unless the COG explicitly forwards another seat's GO or READY token.
WIDTH = {"GATE_SCRIPT_LOADED": 1, "GATE_SPAWN_INVENTORY": 15, "GATE_HELD": 3,
         "GATE_POST_LOADOUT": 16, "GATE_SEND_READY": 4, "GATE_OBS_READY": 3,
         "GATE_COORDINATOR_GO": 2, "GATE_LOCAL_RELEASE": 9, "GATE_UNLOCK_APPLIED": 6,
         "GATE_HOST_GO_SEEN": 3, "GATE_HOST_ACK": 4, "GATE_TRIGGER_DIAG": 5,
         "GATE_HOST_STATE": 3}
LOADOUT = (1, 1, 0, 0, 0, 0, 0, 0, 0, 1, 50, 0, 100, 400, 0)
GO_SIGNAL = (7312, 1, 7312, 2, 7312)
PLAN = re.compile(r"BOT_GEAR \S+ t=([0-9.]+) event=plan item=(\d+) ")
WORLD = "OpenJKDF2: sithWorld_Load -> "


def require(condition, detail):
    if not condition:
        raise ValueError(detail)


class Event(NamedTuple):
    line: int
    values: tuple


def number(token):
    value = float(token)
    require(isfinite(value), "Nonfinite COG value")
    return value


class Log:
    def __init__(self, path, role):
        raw = path.read_bytes()
        self.digest = sha256(raw).hexdigest()
        self.lines = [s.strip() for s in raw.decode("ascii", errors="replace").splitlines() if s.strip()]
        loads = [(i, s[len(WORLD):]) for i, s in enumerate(self.lines) if s.startswith(WORLD)]
        require([name for _, name in loads].count("m10.jkl") == 1 and loads[-1][1] == "m10.jkl",
                "Gate requires one active Canyon Oasis world")
        self.records = defaultdict(list)
        for i, marker in enumerate(self.lines):
            if not marker.startswith("GATE_"):
                continue
            require(i > loads[-1][0] and marker in WIDTH, "Gate marker outside measured map or protocol")
            fields = self.lines[i+1:i+1+WIDTH[marker]]
            require(len(fields) == WIDTH[marker], "Truncated " + marker)
            try:
                vector_index = {"GATE_HELD": 2, "GATE_LOCAL_RELEASE": 7}.get(marker)
                values = tuple(self.vector(s) if index == vector_index else number(s)
                               for index, s in enumerate(fields))
            except ValueError:
                raise ValueError("Malformed " + marker) from None
            self.records[marker].append(Event(i, values))
        loaded = self.one("GATE_SCRIPT_LOADED")
        require(loaded.values == (role,) and all(loaded.line <= row.line for rows in self.records.values()
                                                 for row in rows), "Invalid fixture role or epoch")

    @staticmethod
    def vector(text):
        require(text.startswith("<") and text.endswith(">"), "Invalid position")
        vec = tuple(number(v) for v in text[1:-1].split())
        require(len(vec) == 3, "Invalid position")
        return vec

    def one(self, marker):
        rows = self.records[marker]
        require(len(rows) == 1, "Expected one " + marker)
        return rows[0]

    def go_sender(self):
        rows = [e for e in self.records["GATE_TRIGGER_DIAG"] if e.values[3] == 2]
        require(len(rows) == 1 and rows[0].values == GO_SIGNAL, "Missing or ambiguous coordinator sender")
        return rows[0]


def ready_pair(log, start, end, end_time, seats):
    rows = log.records["GATE_OBS_READY"]
    require(len(rows) == 2 and {r.values[0] for r in rows} == {1, 2}, "Two READY senders required")
    last_time = 0
    for row in rows:
        slot, sent, seen = row.values
        seat = seats[slot]
        require(start < row.line < end and last_time <= seen <= end_time and
                seat["loadout_time_s"] <= sent <= seat["release_time_s"], "Invalid READY ordering or clock")
        last_time = seen
    return [{"slot": int(r.values[0]), "sender_time_s": r.values[1], "observer_time_s": r.values[2]}
            for r in rows]


def owner(log, opening):
    slot = opening["slot"]
    require(log.digest == opening["log_sha256"], "Owner observations came from different logs")
    pose = tuple(opening["events"][0]["position"])
    spawn = log.one("GATE_SPAWN_INVENTORY")
    hold = log.one("GATE_HELD")
    equip = log.one("GATE_POST_LOADOUT")
    go = log.go_sender()
    release = log.one("GATE_LOCAL_RELEASE")
    unlock = log.one("GATE_UNLOCK_APPLIED")
    join_tag = f"BOT_JOINED slot={slot} net={opening['net']}"
    require(log.lines.index(join_tag) < log.one("GATE_SCRIPT_LOADED").line < spawn.line < hold.line
            < log.lines.index("ADJOIN_OPENING") < log.lines.index("ADJOIN_RIFLE_BASE")
            < equip.line < go.line < release.line < unlock.line, "Incorrect owner gate order")
    require(spawn.values == (0,) * 15 and equip.values[1:] == LOADOUT, "Incorrect sampled initial loadout")
    require(hold.values[0] == slot and hold.values[2] == pose, "Hold pose differs from measured opening")
    owner_slot, token, when, samples, bad, drift, turn, locked_pose, rifle = release.values
    require(owner_slot == slot and token > 0 and 0 <= hold.values[1] <= equip.values[0] <= when
            and samples >= 1 and samples.is_integer() and (bad, drift, turn, locked_pose, rifle) == (0, 0, 0, pose, 0),
            "Invalid held pose, inventory, sample or release state")
    require(unlock.values[:5] == (slot, 0, 1, 1, token) and unlock.values[5] >= when,
            "Restored controls, gravity, collision or GO token invalid")
    ready = log.records["GATE_SEND_READY"]
    require(ready and all(equip.line < r.line < go.line and r.values == (slot, 0, 0, 0) for r in ready),
            "Invalid owner READY sample")
    between = log.lines[hold.line:unlock.line]
    require("ADJOIN_RIFLE_CHANGE" not in between and "ADJOIN_RESPAWN" not in between,
            "Inventory changed or owner respawned before unlock")
    states = [s for s in between if s.startswith("BOT_FORCE_STATE ")]
    require(states and all(" immobile=1 " in s and re.search(r" active=0x0+$", s) for s in states),
            "Missing held Force sample or observed active/moving owner")
    require(not any(s.startswith(("BOT_FIRE_INPUT ", "BOT_FORCE_INPUT ")) for s in between),
            "Fire or Force input observed during hold")
    changes = [ev for ev in opening["events"] if ev["kind"] == "sampled_inventory_change"]
    require(all(ev["level_time_s"] >= unlock.values[5] for ev in changes),
            "Inventory sample clock precedes unlock")
    gains = [round(ev["level_time_s"] - when, 6) for ev in changes if ev["current"] == 1]
    plans = [{"item": int(m[2]), "bot_time_s": number(m[1])} for line in between if (m := PLAN.match(line))]
    return {"slot": slot, "net": opening["net"], "gate_token": token, "hold_time_s": hold.values[1],
            "loadout_time_s": equip.values[0], "release_time_s": when, "unlock_time_s": unlock.values[5],
            "held_samples": int(samples), "held_native_force_state_samples": len(states), "owner_ready_reports": len(ready), "pre_release_plans": plans,
            "sampled_position_delta": drift, "sampled_facing_delta": turn, "held_bad_bits": int(bad),
            "restored_actor_bits": int(unlock.values[1]), "restored_gravity": int(unlock.values[2]),
            "restored_collision": int(unlock.values[3]), "sampled_rifle_gains_after_release_s": gains,
            "first_rifle_gain_after_release_s": gains[0] if gains else None}


def qualify(directory, openings):
    """Openings must be produced by controlled_opening.qualify for these exact files."""
    require(set(openings) == {"dark", "light"}, "Two distinct owner logs required")
    logs = {side: Log(directory / (side + ".log"), 0) for side in openings}
    owners = {side: owner(logs[side], op) for side, op in openings.items()}
    seats = {row["slot"]: row for row in owners.values()}
    require(set(seats) == {1, 2} and len({row["net"] for row in seats.values()}) == 2,
            "Two distinct native owners required")
    by_slot = {row["slot"]: logs[side] for side, row in owners.items()}
    go = by_slot[1].one("GATE_COORDINATOR_GO")
    token = go.values[1]
    require(go.values[0] == 3 and 0 < token <= seats[1]["release_time_s"] and
            all(row["gate_token"] == token for row in seats.values()), "Coordinator mask or shared GO token invalid")
    require(go.line < by_slot[1].go_sender().line and not by_slot[2].records["GATE_COORDINATOR_GO"],
            "GO must be issued once by slot one")
    coordinator_ready = ready_pair(by_slot[1], by_slot[1].one("GATE_HELD").line, go.line, token, seats)
    host = Log(directory / "server.log", 1)
    host_go = host.one("GATE_HOST_GO_SEEN")
    sender = host.go_sender()
    mask, host_token, host_time = host_go.values
    require(mask == 3 and host_token == token and sender.line < host_go.line, "Missing matching host GO")
    host_ready = ready_pair(host, host.one("GATE_SCRIPT_LOADED").line, sender.line, host_time, seats)
    mask = 0
    last_time = host_time
    acks = []
    for row in host.records["GATE_HOST_ACK"]:
        slot, reported, ack_token, when = row.values
        require(slot in (1, 2) and not mask & int(slot), "Invalid or duplicate host ACK sender")
        mask |= int(slot)
        require(host_go.line < row.line and last_time <= when and ack_token == token and reported == mask,
                "Invalid host acknowledgement sequence")
        acks.append({"slot": int(slot), "mask": mask, "host_time_s": when})
        last_time = when
    require(mask == 3, "Incomplete host acknowledgements")
    return {"status": "qualified", "gate_token": token, "coordinator_slot": 1, "coordinator_ready": coordinator_ready,
            "host_ready": host_ready, "host_go_time_s": host_time, "host_acknowledgements": acks,
            "host_log_sha256": host.digest, "owners": owners}
