"""Compare the sparse observations from two completed native Canyon Oasis duels."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re


# Stock JK1MP m10.jkl, thing 29 (concrifle) in sector 58. Bin 9 is the rifle.
MAP_HASH = "87bb3e919ee1f3749595f1ee37965bc083dbb866148775fd64280b0170926ecc"
EPISODE_HASH = "27a4b3642e0965753232f35b1e8e846c91df1eca1da77398b5efda66ca369a2e"
HOST = "bin/linux-x86_64/openjkdf2"
MODES = {"BOT_NAV", "BOT_GEAR", "BOT_FORCE_STATE", "BOT_RESPAWN", "BOT_FIRE_INPUT", "BOT_STATUS"}
SIDES = ("dark", "light")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def number(value):
    parsed = float(value)
    require(math.isfinite(parsed), "Nonfinite native observation")
    return parsed


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read_seat(path, name):
    result = dict(name=name, first_gear_plan=None, first_rifle_plan=None, first_rifle_selected_status=None,
                  rifle_fire_input_reports=0, first_rifle_fire_input=None, fire_input_reports=0,
                  resource_decrease_intervals=0, respawn_reports=0, status_samples=[])
    prior_resources = None
    last_state_time = None
    map_seen = False
    result["join_acknowledgements"] = []
    with path.open(encoding="utf-8", errors="replace") as lines:
        for line in lines:
            kind, _, tail = line.strip().partition(" ")
            if kind == "BOT_JOINED":
                ack = re.fullmatch(r"slot=(\d+) net=(\d+)", tail)
                require(ack is not None, "Invalid native join acknowledgement")
                result["join_acknowledgements"].append(dict(slot=int(ack[1]), net=int(ack[2])))
                continue
            if kind not in MODES:
                continue
            fields = dict(re.findall(r"(\w+)=([^\s]+)", tail))
            require(fields.get("name") == name, "Mixed or unexpected seat in " + path.name)
            if kind == "BOT_NAV":
                require(fields.get("map", "").casefold() == "m10.jkl" and not map_seen,
                        "Unexpected map or restarted seat")
                map_seen = True
            elif kind == "BOT_RESPAWN":
                result["respawn_reports"] += 1
                prior_resources = None
            elif kind == "BOT_GEAR" and fields["event"] == "plan":
                plan = dict(t=number(fields["t"]), item=int(fields["item"]))
                if result["first_gear_plan"] is None:
                    result["first_gear_plan"] = plan
                if plan["item"] == 29 and fields.get("pack") == "0" and result["first_rifle_plan"] is None:
                    result["first_rifle_plan"] = plan
            elif kind == "BOT_FIRE_INPUT":
                result["fire_input_reports"] += 1
                if int(fields["weapon"]) == 9:
                    result["rifle_fire_input_reports"] += 1
                    if result["first_rifle_fire_input"] is None:
                        result["first_rifle_fire_input"] = dict(t=number(fields["t"]), alternate=int(fields["alternate"]))
            elif kind == "BOT_FORCE_STATE":
                t = number(fields["t"])
                require(last_state_time is None or t > last_state_time, "Restarted or duplicate state sample")
                last_state_time = t
                cur = (number(fields["health"]), number(fields["shields"]))
                if prior_resources and any(a < b for a, b in zip(cur, prior_resources)):
                    result["resource_decrease_intervals"] += 1
                prior_resources = cur
            elif kind == "BOT_STATUS":
                sample = {key: int(fields[key]) for key in ("sector", "weapon", "goal", "following", "kills", "deaths")}
                sample.update(t=number(fields["t"]), position=[number(v) for v in fields["pos"].split(",")])
                samples = result["status_samples"]
                require(len(sample["position"]) == 3 and (not samples or sample["t"] > samples[-1]["t"]),
                        "Invalid position or non-increasing status time")
                samples.append(sample)
                if sample["weapon"] == 9 and result["first_rifle_selected_status"] is None:
                    result["first_rifle_selected_status"] = {key: sample[key] for key in ("t", "sector")}
    require(map_seen and result["status_samples"] and last_state_time is not None, "Incomplete native observation")
    return result


def compare_seat(a, b):
    require(a["name"] == b["name"], "Seat identity changed between duels")
    result = {"first_status_difference": None,
              "first_gear_items": [s["first_gear_plan"]["item"] if s["first_gear_plan"] else None for s in (a, b)],
              "status_sample_counts": [len(s["status_samples"]) for s in (a, b)]}
    for index, (first, repeat) in enumerate(zip(a["status_samples"], b["status_samples"]), 1):
        changed = [k for k in first if k != "t" and first[k] != repeat[k]]
        if changed:
            result["first_status_difference"] = {"ordinal": index, "local_times": [first["t"], repeat["t"]],
                                                 "fields": changed, "values": {k: [first[k], repeat[k]] for k in changed}}
            break
    return result


def read_observer(directory, receipt, names, *, sides=SIDES):
    camera_path = directory / "spectator" / "observer-receipt.json"
    require(sha(camera_path) == receipt["observer_receipt_sha256"], "Observer receipt hash mismatch")
    camera = json.loads(camera_path.read_bytes())
    require(receipt["observer_status"] == camera["status"] == "recorded"
            and camera["match"]["map"] == "m10.jkl" and camera["match"]["engine_sha256"] == receipt["sha256"][HOST],
            "Incomplete or different observer session")
    players = sorted(camera["joined_roster"], key=lambda p: p["slot"])
    roster = [p["name"] for p in players]
    require(roster == names, "Host roster differs from peer logs")
    for side, player in zip(sides, players, strict=True):
        require(receipt["bots"][side]["joined"] == {"slot": player["slot"], "net": player["peer_id"]},
                "Host and peer identity differ")
    clip = camera["video"]
    mode = camera.get("camera", "follow")
    require(mode in {"rifle-overlook", "follow"}, "Unknown native observer camera")
    clip_path = camera_path.with_name(f"native-{mode}.mp4")
    require(clip["decoded_fully"] and sha(clip_path) == clip["sha256"],
            "Unverified observer video")
    video = dict(sha256=clip["sha256"], frames=int(clip["stream"]["nb_frames"]),
                 seconds=number(clip["stream"]["duration"]), receipt_sha256=sha(camera_path))
    frames = camera["captured"]
    require(len(frames) == video["frames"] and len(frames) >= 3, "Observer frame count mismatch")
    sectors = [frame["pose"]["sector"] for frame in frames if frame.get("pose")]
    video.update(camera=mode, valid_camera_poses=len(sectors))
    if mode == "follow":
        followed = camera["followed"]
        require(followed in players, "Follow camera identity missing from the host roster")
        video.update(followed=followed["name"], poses_in_rifle_sector=sectors.count(58),
                     first_camera_sector=sectors[0] if sectors else None)
    else:
        require(camera["overlook"]["settled_pose"]["sector"] == 41 and sectors and set(sectors) == {41},
                "Rifle camera outside its measured observation sector")
        video["station_sector"] = 41
    return roster, video


def read_run(directory):
    file = directory / "receipt.json"
    receipt = json.loads(file.read_bytes())
    require(receipt.get("kind") == "adjoin-arena-native-duel" and receipt.get("network_interfaces") == ["lo"]
            and receipt.get("pacing") == "normal engine wall-clock", "Requires an isolated loopback 1x arena")
    hashes = receipt["sha256"]
    require(receipt["status"] == "live_join_and_loadout_verified" and hashes.get("jk1mp.gob") == EPISODE_HASH
            and hashes.get("jkl/m10.jkl") == MAP_HASH
            and receipt.get("dedicated_server_owned_udp_port") is True, "Requires a completed stock Canyon Oasis run")
    registry = receipt["server_registry"].copy()
    port = registry.pop("portNum")
    require(registry["bIsDedicated"] and registry["serverMapJkl"].casefold() == "m10.jkl", "Unexpected server config")
    server = directory / "server.log"
    joins = re.findall(r"^\s*(\S+) has joined the game\s*$", server.read_text(errors="replace"), re.MULTILINE)
    roster, video = [], None
    seats, args_by_seat = {}, {}
    log_hashes = {"server.log": sha(server)}
    for side in SIDES:
        args = list(receipt["bots"][side]["argv"])
        name = args[args.index("-botName") + 1]
        endpoint = args.index("-botConnect") + 1
        require(args[endpoint] == f"127.0.0.1:{port}", "Peer endpoint differs from the host")
        args[endpoint] = "loopback"
        args_by_seat[side] = args
        log = directory / (side + ".log")
        log_hashes[log.name] = sha(log)
        seats[side] = read_seat(log, name)
        require(seats[side]["join_acknowledgements"] == [receipt["bots"][side]["joined"]],
                "Missing or conflicting peer join acknowledgement")
    joined = [s["join_acknowledgements"][0] for s in seats.values()]
    require(all(len({peer[key] for peer in joined}) == 2 for key in ("slot", "net")),
            "Duplicate peer join acknowledgement")
    for name, digest in log_hashes.items():
        require(digest == receipt["log_sha256"].get(name), "Log hash differs from launch receipt: " + name)
    names = [seats[s]["name"] for s in SIDES]
    require(len(set(names)) == 2 and len(joins) == len(set(joins)) and set(joins) <= set(names),
            "Unexpected or repeated host join")
    if receipt.get("observer_receipt_sha256"):
        roster, video = read_observer(directory, receipt, names)
    require(roster == names or joins == names, "Need two host joins or a verified host roster")
    config = dict(registry=registry, peers=args_by_seat, bot_options=receipt["bot_options"], sha256=hashes,
                  launcher_sha256=receipt["launcher_sha256"], launcher_inputs=receipt["launcher_input_sha256"],
                  recorder_sha256=receipt.get("recorder_sha256"), render_environment=receipt.get("render_environment"),
                  camera=video["camera"] if video else None,
                  requested_seconds=receipt["requested_match_seconds"])
    return dict(receipt_sha256=sha(file), logs_sha256=log_hashes, host_console_joins=joins,
                host_roster=roster, video=video, seats=seats), config


def compare_runs(first_dir, repeat_dir):
    require(not first_dir.samefile(repeat_dir), "Provide two different run directories")
    a, first_config = read_run(first_dir)
    b, repeat_config = read_run(repeat_dir)
    require(first_config == repeat_config, "Game, build, duration or seat settings differ")
    require(a["receipt_sha256"] != b["receipt_sha256"], "Duplicate run receipt")
    return dict(schema=1, scope="Two 1x native runs, rounded peer-local samples and input reports",
                configuration=first_config, runs=[a, b],
                comparison={s: compare_seat(a["seats"][s], b["seats"][s]) for s in SIDES})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--first", type=Path, required=True)
    parser.add_argument("--repeat", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="New JSON output file")
    args = parser.parse_args()
    try:
        report = compare_runs(args.first, args.repeat)
        with args.output.open("x", encoding="utf-8", newline="\n") as f:
            json.dump(report, f, indent=2, allow_nan=False)
            f.write("\n")
    except (OSError, ValueError, KeyError, IndexError, TypeError) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
