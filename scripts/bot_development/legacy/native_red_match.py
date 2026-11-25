"""Evidence from ordinary stock spawns of two native Red-policy players."""
from collections import Counter
import json

TEACHER_REVISION = "f453778a3cf670dea43c44315786ae4afc8ae440"
TEACHER_OVERLAY = "0e409e379d0e6f088d9ddf469aaac54dc301e0111ce0ce08c5823d210f1857aa"
RED_BASE_PATCH = "6950c859f9e82aca8285daac011e1b72cb2a57644f01d2a465987312100ac52d"
RED_ARCHIVE = "ca63beaa5c3a283639950be045df0d5ffa5a2fb39cc259db479c3deee4a4a123"


def resolve_client(repo, directory, pace_build, digest, *, transfer=False, custom=False, platform_build=False,
                   hint_build=False):
    manifest_name = "red-transfer-build.json" if transfer else "red-policy-build.json"
    if custom:
        if not transfer:
            raise ValueError("custom admission requires the transfer client")
        manifest_name = "red-custom-build.json"
    if platform_build:
        if not custom:
            raise ValueError("platform support requires the custom-admission client")
        manifest_name = "red-platform-build.json"
    if hint_build:
        if not platform_build:
            raise ValueError("route hints require the platform-aware client")
        manifest_name = "red-hint-build.json"
    manifest = repo / "native" / manifest_name
    build = json.loads(manifest.read_bytes())
    client = directory / "jk-bot-client"
    library = directory / "libGameNetworkingSockets.so"
    pins = {"native/red_policy.inc": "policy_source_sha256", "native/red-policy.patch": "policy_patch_sha256",
            "native/build_red_policy.py": "builder_sha256", "native/arena_pace.c": "pace_source_sha256",
            "native/pace-build.json": "pace_receipt_sha256"}
    if transfer:
        pins.update({"native/red-policy-build.json":"duel_receipt_sha256","native/red-transfer.patch":"transfer_patch_sha256",
                     "native/red_transfer.inc":"transfer_source_sha256","native/red_nav_recall.h":"nav_recall_sha256",
                     "native/build_red_transfer.py":"transfer_builder_sha256"})
    if custom:
        pins.update({"native/red-transfer-build.json": "transfer_receipt_sha256",
                     "native/red-custom.patch": "custom_patch_sha256",
                     "native/red_custom.h": "custom_source_sha256",
                     "native/build_red_custom.py": "custom_builder_sha256"})
    if platform_build:
        pins.update({"native/red-custom-build.json": "custom_receipt_sha256",
                     "native/red-platform.patch": "platform_patch_sha256",
                     "native/red_platform.inc": "platform_source_sha256",
                     "native/build_red_platform.py": "platform_builder_sha256"})
        previous = json.loads((repo / "native/red-custom-build.json").read_bytes())
        if build.get("custom_binary_sha256") != previous["binary_sha256"]:
            raise ValueError("native_platform_base_client_mismatch")
    if hint_build:
        pins.update({"native/red-platform-build.json": "platform_receipt_sha256",
                     "native/red-hint.patch": "hint_patch_sha256",
                     "native/red_hint.inc": "hint_source_sha256",
                     "native/build_red_hint.py": "hint_builder_sha256"})
        previous = json.loads((repo / "native/red-platform-build.json").read_bytes())
        if build.get("platform_binary_sha256") != previous["binary_sha256"]:
            raise ValueError("native_hint_base_client_mismatch")
    if (digest(directory / manifest.name) != digest(manifest)
            or any(digest(repo / name) != build[key] for name, key in pins.items())
            or build["red_commit"] != TEACHER_REVISION or build["red_overlay_sha256"] != TEACHER_OVERLAY
            or build["archive_sha256"] != RED_ARCHIVE or build["base_patch_sha256"] != RED_BASE_PATCH
            or digest(client) != build["binary_sha256"] or digest(library) != build["gns_sha256"]
            or build["gns_sha256"] != pace_build["bot"]["gns_sha256"]):
        raise ValueError("native_red_client_or_provenance_mismatch")
    return client, build


def fields(line):
    return dict(token.split("=", 1) for token in line.split()[1:] if "=" in token)


def read_owner(path):
    events = {}
    movements = []
    decisions = Counter()
    observed = {"weapon_gains": [], "health_loss": 0.0, "shield_loss": 0.0,
                "kill_increments": 0, "death_increments": 0, "samples": 0}
    previous_state = None
    status = None
    health = []
    shield = []
    respawns = shots = 0
    for line_num, raw in enumerate(path.read_bytes().splitlines(), 1):
        line = raw.strip().decode("ascii", "replace")
        tag = line.partition(" ")[0]
        if tag in ("BOT_RED_JOIN", "BOT_RED_FIRST", "BOT_RED_APPLY", "BOT_RED_MODEL"):
            detail = dict(line=line_num, **fields(line))
            events.setdefault(tag, detail)
            if tag == "BOT_RED_APPLY":
                movements.append(detail)
        elif tag == "BOT_DUEL":
            d = fields(line)
            if "teacher" in d:
                decisions[d["teacher"]] += 1
        elif tag == "BOT_STATUS":
            status = fields(line)
        elif tag == "BOT_RED_STATE":
            d = fields(line)
            state = {k:int(d[k]) for k in ("life","game_ms","mono_ns","kills","deaths","dead")}
            state.update(hp=float(d["hp"]), shields=float(d["shields"]), weapons=int(d["weapons"], 0))
            observed["samples"] += 1
            if previous_state is None:
                observed["first_state"] = state
            else:
                for field, increment in (("kills","kill_increments"), ("deaths","death_increments")):
                    observed[increment] += max(0, state[field] - previous_state[field])
                if state["life"] == previous_state["life"] and not previous_state["dead"]:
                    observed["health_loss"] += max(0, previous_state["hp"] - state["hp"])
                    observed["shield_loss"] += max(0, previous_state["shields"] - state["shields"])
                    if not state["dead"]:
                        gained = state["weapons"] & ~previous_state["weapons"]
                        observed["weapon_gains"].extend(
                            {"bin": b, "life": state["life"], "game_ms": state["game_ms"], "line": line_num}
                            for b in range(1, 11) if gained & (1 << b))
            previous_state = state
        elif tag == "BOT_RESPAWN":
            respawns += 1
        elif tag == "BOT_FIRE_INPUT":
            shots += 1
        elif tag == "BOT_FORCE_STATE":
            sample = fields(line)
            health.append(float(sample["health"]))
            shield.append(float(sample["shields"]))
        elif tag in ("GATE_HELD", "GATE_LOCAL_RELEASE", "BOT_PLANNER_GATE", "ADJOIN_OPENING"):
            raise ValueError("native_red_unexpected_start_gate")
    if previous_state is not None:
        observed["last_state"] = previous_state
    return dict(events=events, first_movement_by_life=movements, teacher_labels=dict(decisions), owner_state=observed,
                last_native_score_sample={k:int(status[k]) for k in ("kills","deaths")} if status else None,
                last_native_score_sample_t=float(status["t"]) if status else None,
                observed_respawns=respawns, fire_input_events=shots,
                health_drops=sum(b<a for a,b in zip(health,health[1:])),
                shield_drops=sum(b<a for a,b in zip(shield,shield[1:])))


def first_controls(directory, receipt):
    evidence = {}
    for side in ("dark", "light"):
        data = read_owner(directory / (side + ".log"))
        events = data["events"]
        if not all(tag in events for tag in ("BOT_RED_JOIN", "BOT_RED_FIRST", "BOT_RED_APPLY", "BOT_RED_MODEL")):
            raise ValueError("native_red_missing_immediate_start_evidence")
        join, first, move = (events[tag] for tag in ("BOT_RED_JOIN","BOT_RED_FIRST","BOT_RED_APPLY"))
        pid = receipt["pace_experiment"]["loaded_images"][side]["pid"]
        model = events["BOT_RED_MODEL"]
        learned = side == receipt["red_policy"]["model_side"]
        if (int(model["pid"]) != pid or model["mode"] != ("learned" if learned else "teacher")
                or model["model"] != (receipt["red_policy"]["weights_sha256"] if learned else "teacher")
                or model["status"] != "ready"):
            raise ValueError("native_red_model_rejected_or_mismatched")
        if data["owner_state"]["samples"] < 2:
            raise ValueError("native_red_missing_inventory_and_score_state")
        times = [int(row["mono_ns"]) for row in (join,first,move)]
        if (any(int(row["pid"]) != pid for row in (join,first,move)) or times != sorted(times)
                or int(join["slot"]) != receipt["bots"][side]["joined"]["slot"]
                or int(move["frame"]) < int(first["frame"])
                or (float(move["fwd"]) == 0 and float(move["slide"]) == 0)):
            raise ValueError("native_red_owner_control_identity_or_time_mismatch")
        data.update(join_to_eligible_wall_s=(times[1]-times[0])/1e9,
                    eligible_to_movement_wall_s=(times[2]-times[1])/1e9,
                    eligible_to_movement_frames=int(move["frame"])-int(first["frame"]))
        evidence[side] = data
    a,b=sorted(evidence, key=lambda side:receipt["bots"][side]["joined"]["slot"])
    gap=(int(evidence[b]["events"]["BOT_RED_JOIN"]["mono_ns"])-int(evidence[a]["events"]["BOT_RED_APPLY"]["mono_ns"]))/1e9
    if gap <= 0:
        raise ValueError("native_red_first_seat_motion_not_before_second_join")
    host_pid = receipt["pace_experiment"]["loaded_images"]["host"]["pid"]
    with (directory / "pace-trace.jsonl").open() as trace:
        first_host_tick = next((tick for line in trace if (tick := json.loads(line))["role"] == "host"), None)
    if (not first_host_tick or first_host_tick["pid"] != host_pid
            or first_host_tick["mono_ns"] >= int(evidence[b]["events"]["BOT_RED_JOIN"]["mono_ns"])):
        raise ValueError("native_red_host_did_not_tick_before_second_join")
    return dict(owners=evidence, first_seat_move_before_second_join_wall_s=gap,
                host_first_tick=first_host_tick)
