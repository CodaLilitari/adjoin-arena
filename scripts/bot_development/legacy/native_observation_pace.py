"""Collect engine-clock observations for a two-peer, isolated native pace experiment."""
import json
import re

ROLES = ("host", "dark", "light")
MARKER = re.compile(r"ARENA_PACE role=(host|dark|light) pid=(\d+) rate=(\d+) frame=(\d+) "
                    r"game_ms=(\d+) mono_ns=(\d+) step_ms=(\d+) applied_ms=(\d+)")


def resolve_build(repo, directory, hashes, digest):
    manifest = repo / "native/pace-build.json"
    meta = json.loads(manifest.read_bytes())
    host = directory / "host/openjkdf2"
    bot = directory / "bot/jk-bot-client"
    planner = json.loads((repo / "native/planner-go-build.json").read_bytes())
    published = json.loads((repo / "native/BUILD.json").read_bytes())["files"]
    bots = json.loads((repo / "native/BOT_BUILD.json").read_bytes())["files"]
    resources = {"native/arena_pace.c": meta["pace_source_sha256"],
                 "native/build_arena_pace.py": meta["builder_sha256"],
                 "native/relink-linux-x86_64.tar.gz": meta["host"]["archive_sha256"],
                 "native/bot-relink-linux-x86_64.tar.gz": meta["bot"]["archive_sha256"]}
    library = "libGameNetworkingSockets.so"
    if (digest(manifest) != digest(directory / "pace-build.json")
            or meta["schema"] != 1 or meta["step_ms"] != 34 or meta["rates"] != [1, 2]
            or any(digest(repo / name) != value for name, value in resources.items())
            or resources["native/relink-linux-x86_64.tar.gz"] != published["native/relink-linux-x86_64.tar.gz"]["sha256"]
            or resources["native/bot-relink-linux-x86_64.tar.gz"] != bots["native/bot-relink-linux-x86_64.tar.gz"]["sha256"]
            or meta["host"]["base_binary_sha256"] != hashes["bin/linux-x86_64/openjkdf2"]
            or meta["host"]["base_binary_sha256"] != published["bin/linux-x86_64/openjkdf2"]["sha256"]
            or meta["bot"]["base_binary_sha256"] != planner["binary_sha256"]
            or meta["bot"]["planner_object_sha256"] != planner["rebuilt_object_sha256"]
            or planner["patch_sha256"] != digest(repo / "native/planner-go.patch")
            or meta["host"]["gns_sha256"] != hashes["bin/linux-x86_64/" + library]
            or meta["host"]["gns_sha256"] != published["bin/linux-x86_64/" + library]["sha256"]
            or meta["bot"]["gns_sha256"] != planner["gns_sha256"]
            or meta["bot"]["gns_sha256"] != hashes["bin/bots-linux-x86_64/" + library]):
        raise ValueError("native_pace_build_or_provenance_mismatch")
    for role, executable in (("host", host), ("bot", bot)):
        if (digest(executable) != meta[role]["binary_sha256"]
                or digest(executable.parent / library) != meta[role]["gns_sha256"]):
            raise ValueError("native_pace_executable_or_networking_library_mismatch")
    hashes.update(resources)
    hashes["native/pace-build.json"] = digest(manifest)
    return host, bot, meta


class NativePace:
    def __init__(self, trace, experiment):
        self.trace = trace
        self.experiment = experiment
        self.acks = 0
        self.released = set()
        self.first = {}
        self.latest = {}
        self.last = {}
        self.start = None

    def observe(self, role, pid, line):
        if role == "host" and line == "GATE_HOST_ACK":
            self.acks += 1
        if (role in ("dark", "light") and line.startswith("BOT_PLANNER_GATE ")
                and " mode=on phase=released " in line):
            self.released.add(role)
        if not line.startswith("ARENA_PACE "):
            return
        match = MARKER.fullmatch(line)
        if not match:
            raise ValueError("native_pace_malformed_sample")
        label, number, rate, frame, game, wall, step, applied = match.groups()
        row = dict(role=label, pid=int(number), rate=int(rate), frame=int(frame),
                   game_ms=int(game), mono_ns=int(wall), step_ms=int(step), applied_ms=int(applied))
        if (label != role or row["pid"] != pid or row["rate"] != self.experiment["speed"]
                or row["step_ms"] != 34):
            raise ValueError("native_pace_identity_rate_or_step_mismatch")
        self.trace.write(json.dumps(row, separators=(",", ":")) + "\n")
        if self.start is None or row["mono_ns"] < self.start:
            return
        if row["applied_ms"] != row["step_ms"]:
            raise ValueError("native_pace_engine_step_mismatch")
        prev = self.latest.get(role)
        if prev and (row["frame"] <= prev["frame"] or row["game_ms"] <= prev["game_ms"]
                     or row["mono_ns"] <= prev["mono_ns"]):
            raise ValueError("native_pace_did_not_advance")
        if prev and (row["frame"] - prev["frame"] != 5 or row["game_ms"] - prev["game_ms"] != 170):
            raise ValueError("native_pace_missing_or_inconsistent_frame_samples")
        self.latest[role] = row
        first = self.first.setdefault(role, row)
        if row["game_ms"] - first["game_ms"] >= 1000 * self.experiment["requested_game_seconds"]:
            self.last.setdefault(role, row)

    def poll(self, now_ns):
        if self.start is None and self.acks >= 2 and self.released == {"dark", "light"}:
            self.start = self.experiment["start_monotonic_ns"] = now_ns
        return len(self.last) == len(ROLES)

    def finish(self, now_ns):
        self.experiment["end_monotonic_ns"] = now_ns
        result = self.experiment["roles"] = {}
        speed = self.experiment["speed"]
        target = self.experiment["requested_game_seconds"]
        for role in ROLES:
            first, last, final = self.first[role], self.last[role], self.latest[role]
            elapsed = (last["game_ms"] - first["game_ms"]) / 1000
            wall = (last["mono_ns"] - first["mono_ns"]) / 1e9
            rate = elapsed / wall
            tail = (final["game_ms"] - first["game_ms"]) / 1000 - target
            result[role] = dict(pid=first["pid"], first=first, last=last, final_sample=final,
                                measured_game_s=elapsed, measured_wall_s=wall, observed_rate=rate,
                                observed_game_tail_s=tail)
        if any(not (0.9 * speed <= entry["observed_rate"] <= 1.1 * speed) for entry in result.values()):
            raise ValueError("native_pace_outside_requested_band")
        if any(not (0 <= entry["observed_game_tail_s"] <= .65) for entry in result.values()):
            raise ValueError("native_pace_game_window_exceeded")
