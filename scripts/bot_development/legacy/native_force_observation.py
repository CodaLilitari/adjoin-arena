#!/usr/bin/env python3
"""Observe two native JK clients in a bounded Linux Force test.

The caller supplies the repository, owned game installation and a fresh output
directory. This is a development observation, not a competitive-skill verdict.
"""
import argparse
from collections import Counter
from contextlib import nullcontext
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import signal
import socket
import subprocess
import sys
import tempfile
import time

BOT = "bin/bots-linux-x86_64/jk-bot-client"
SERVER = "bin/linux-x86_64/openjkdf2"
PATCH = "native/bot-client.patch"
GNS = "libGameNetworkingSockets.so"
STOCK_MP = "27a4b3642e0965753232f35b1e8e846c91df1eca1da77398b5efda66ca369a2e"
STOCK_MAPS = ("m2.jkl", "m4.jkl", "m5.jkl", "m10.jkl", "m_boss15.jkl", "m_boss17.jkl")
EXPECTED = {"light": {21, 22, 23, 24, 25, 28}, "dark": {21, 22, 23, 24, 31, 33}}
FLAGS = {"SDL_VIDEODRIVER": "offscreen", "SDL_VIDEO_DRIVER": "offscreen",
         "EGL_PLATFORM": "surfaceless", "LIBGL_ALWAYS_SOFTWARE": "1",
         "ALSOFT_DRIVERS": "null", "SDL_AUDIODRIVER": "dummy", "LP_NUM_THREADS": "2"}
START = time.monotonic()
STOP = []
CHILDREN = {}
READERS = {}
LABELS = {"dark": "boba_fett", "light": "jan_ors"}


class Failure(Exception):
    """A public error string assembled only from non-sensitive fields."""


def check():
    if STOP:
        raise Failure("interrupted_signal_%d" % STOP[0])
    if time.monotonic() - START >= 172:
        raise Failure("overall_deadline")


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as inp:
        while block := inp.read(1024 * 1024):
            check()
            value.update(block)
    return value.hexdigest()


def dump(value):
    return json.dumps(value, separators=(",", ":"), allow_nan=False)


def choose(directory, name):
    matches = [p for p in directory.iterdir() if p.name.casefold() == name]
    if len(matches) != 1:
        raise Failure("missing_or_ambiguous_" + name)
    return matches[0]


def stage(source, target, *, stock_episode=True):
    # Private copies only. prepare_bot can then safely hard-link *these* inputs.
    for name in ("resource", "episode"):
        (target / name).mkdir(parents=True)
    resource = choose(source, "resource")
    variants = [n for n in ("res1hi.gob", "res1.gob", "res1low.gob")
                if any(p.name.casefold() == n for p in resource.iterdir())]
    if not variants:
        raise Failure("missing_stock_resource_gob")
    files = [("resource", resource, "res2.gob"), ("resource", resource, variants[0]),
             ("resource", resource, "jk_.cd")]
    if stock_episode:
        files.append(("episode", choose(source, "episode"), "jk1mp.gob"))
    for section, parent, name in files:
        check()
        with choose(parent, name).open("rb") as src, (target / section / name).open("xb") as dst:
            while chunk := src.read(1024 * 1024):
                check()
                dst.write(chunk)


def boot(label, command, directory, env, output, recorder=None, repo=None, camera="follow", line_buffered=False):
    path = output / (label + ".log")
    with path.open("xb") as log:
        if recorder is None:
            if line_buffered:
                command = ["stdbuf", "-oL", *command]
            child = subprocess.Popen(command, cwd=directory, stdin=subprocess.DEVNULL,
                                     stdout=log, stderr=subprocess.STDOUT, env=env,
                                     start_new_session=True)
        else:
            child = recorder.boot_server(command, directory, env, log, repo, output, camera=camera,
                                         line_buffered=line_buffered)
        CHILDREN[label] = child
    READERS[label] = path.open("rb")


def shutdown():
    # Signal all private sessions together, including descendants of exited leaders.
    def send(sig):
        for child in CHILDREN.values():
            try:
                os.killpg(child.pid, sig)
            except ProcessLookupError:
                pass
    send(signal.SIGTERM)
    end = time.monotonic() + 1
    while time.monotonic() < end and any(p.poll() is None for p in CHILDREN.values()):
        time.sleep(.03)
    send(signal.SIGKILL)
    for child in CHILDREN.values():
        child.wait(timeout=1)
    for reader in READERS.values():
        reader.close()


def owns_udp(pid, port):
    sockets = set()
    for path in Path(f"/proc/{pid}/fd").iterdir():
        try:
            target = os.readlink(path)
        except FileNotFoundError:
            continue
        if target.startswith("socket:["):
            sockets.add(target[8:-1])
    for table in ("udp", "udp6"):
        path = Path(f"/proc/{pid}/net/{table}")
        if path.exists():
            for line in path.read_text().splitlines()[1:]:
                fields = line.split()
                if int(fields[1].split(":")[1], 16) == port and fields[9] in sockets:
                    return True
    return False


def private_env(directory, engine):
    # Do not pass through gateway, proxy, desktop, credential or gameplay settings.
    env = dict(FLAGS, PATH=os.defpath, LANG="C", HOME=str(directory),
               OPENJKDF2_ROOT=str(directory), XDG_RUNTIME_DIR=str(directory / "xdg"),
               XDG_CONFIG_HOME=str(directory / "config"), XDG_DATA_HOME=str(directory / "data"),
               XDG_CACHE_HOME=str(directory / "cache"), TMPDIR=str(directory / "tmp"),
               LD_LIBRARY_PATH=str(engine.parent))
    for child in ("xdg", "config", "tmp", "data", "cache"):
        (directory / child).mkdir(exist_ok=True)
    return env


def loaded_images(proc, engine, expected_engine, expected_library):
    """Verify the running executable and the mapped networking library of this owned Linux process."""
    library = engine.parent / GNS
    info = library.stat()
    expected_file = (os.major(info.st_dev), os.minor(info.st_dev), info.st_ino)
    mapped_files = set()
    for line in (proc / "maps").read_text().splitlines():
        fields = line.split(maxsplit=5)
        if len(fields) == 6 and Path(fields[5]).name == GNS:
            major, minor = (int(part, 16) for part in fields[3].split(":"))
            mapped_files.add((major, minor, int(fields[4])))
    actual = digest(proc / "exe")
    if mapped_files != {expected_file} or actual != expected_engine or digest(library) != expected_library:
        raise Failure("running_native_image_or_networking_library_mismatch")
    return {"executable_sha256": actual, "networking_library_sha256": expected_library}


def research_client(repo, client, packaged, hashes):
    """Bind an externally built research binary to the canonical source and published base build."""
    client = client.resolve(strict=True)
    manifest = repo / "native/planner-go-build.json"
    manifest_hash = digest(manifest)
    if manifest_hash != digest(client.parent / "planner-build.json"):
        raise Failure("research_build_manifest_mismatch")
    build = json.loads(manifest.read_bytes())
    archive = "native/bot-relink-linux-x86_64.tar.gz"
    overlay = "native/planner-go.patch"
    lib_path = str(Path(BOT).parent / GNS)
    binary_hash = digest(client)
    source_hash = digest(repo / overlay)
    archive_hash = digest(repo / archive)
    if (client.name != "jk-bot-client" or build["source_commit"] != packaged["base_commit"]
            or build["patch"] != overlay or build["patch_sha256"] != source_hash
            or build["binary_sha256"] != binary_hash or binary_hash == hashes[BOT]
            or build["base_binary_sha256"] != hashes[BOT] or build["base_patch_sha256"] != hashes[PATCH]
            or build["gns_sha256"] != hashes[lib_path] or digest(client.parent / GNS) != hashes[lib_path]
            or build["relink_archive_sha256"] != archive_hash
            or packaged["files"][archive]["sha256"] != archive_hash or not build["toolchain"]):
        raise Failure("research_binary_or_source_pin_mismatch")
    host_build = json.loads((repo / "native/BUILD.json").read_bytes())
    for path in (SERVER, str(Path(SERVER).parent / GNS)):
        if host_build["files"][path]["sha256"] != hashes[path]:
            raise Failure("research_host_or_networking_library_mismatch")
    hashes.update({overlay: source_hash, archive: archive_hash, "native/planner-go-build.json": manifest_hash,
                   "research/jk-bot-client": binary_hash, "research/" + GNS: hashes[lib_path]})
    return client, build


def check_liveness():
    check()
    for label, process in CHILDREN.items():
        code = process.poll()
        if code is not None:
            raise Failure(f"{label}_exited_{code}")


def new_stats(side):
    return {"side": side, "joined": None, "loadout": None, "behavior": None,
            "samples": 0, "matching_star_samples": 0, "first_stars": None,
            "input_counts": Counter(), "active_counts": Counter(), "immobile_samples": 0,
            "ranges": {}, "mana_decreases": 0, "health_decreases": 0,
            "target_slots": [], "examples": {}, "previous": {}}


def observe(side, name, line, row, trace):
    # Save only typed numeric evidence. Native logs stay private, outside the receipt.
    kind, _, tail = line.partition(" ")
    fields = dict(part.split("=", 1) for part in tail.split() if "=" in part)
    if kind == "BOT_JOIN_REJECTED":
        raise Failure(side + "_join_rejected")
    if kind == "BOT_LOADOUT":
        rank=row.get("expected_rank",8)
        style = row.get("expected_style", "competitive")
        unspent = 8 if style == "master" and rank == 8 else 0
        if not re.fullmatch(f"rank={rank} side={side} style={style} spent={3*rank-unspent} remaining={unspent}", tail):
            raise Failure(side + "_incorrect_saved_plan")
        row["loadout"] = {"rank": rank, "style": style, "spent": 3*rank-unspent, "remaining": unspent}
    if kind == "BOT_JOINED":
        slot, net = int(fields["slot"]), int(fields["net"])
        if not 0 <= slot < 32 or not 0 < net <= 0xffffffff:
            raise Failure(side + "_invalid_join_identity")
        row["joined"] = {"slot": slot, "net": net}
    if fields.get("name") != name:
        return
    if kind == "BOT_BEHAVIOR":
        row["behavior"] = {k: int(fields[k]) for k in ("sabers_only", "fists_peace", "force_enabled")}
    if not row["joined"]:
        return
    if kind == "BOT_STATUS":
        slot = int(fields["target"])
        if slot >= 0 and slot not in row["target_slots"]:
            row["target_slots"].append(slot)
    if kind == "BOT_FORCE_INPUT":
        bin_id = int(fields["bin"])
        row["input_counts"][bin_id] += 1
        event = {k: float(fields[k]) for k in ("mana", "level", "hold")}
        trace.write(dump(dict(event, side=side, event="input", bin=bin_id,
                              read_elapsed_s=round(time.monotonic()-START,3)))+"\n")
    if kind != "BOT_FORCE_STATE":
        return
    sample = {k: float(fields[k]) for k in ("t", "health", "shields", "mana")}
    stars = [float(s) for s in fields["stars"].split(",")]
    if len(stars) != 14 or not all(math.isfinite(v) for v in [*stars, *sample.values()]):
        raise Failure(side + "_invalid_sample")
    sample.update({k: int(fields[k]) for k in ("thing", "guid", "blind", "immobile")})
    mask = int(fields["active"], 16)
    trace.write(dump(dict(sample, side=side, event="state", stars=stars, active=mask,
                          read_elapsed_s=round(time.monotonic()-START,3)))+"\n")
    row["samples"] += 1
    row["first_stars"] = row["first_stars"] or stars
    expected = set(range(25, 30)) if row.get("expected_style") == "master" else EXPECTED[side]
    row["matching_star_samples"] += stars == [4 if row.get("expected_rank",8) and b in expected else 0 for b in range(21,35)]
    row["immobile_samples"] += sample["immobile"] == 1
    prev = row["previous"]
    example = {k:sample[k] for k in ("t","health","shields","mana","immobile")}
    example["active"] = mask
    for label, condition in (("first_active",mask), ("first_immobile",sample["immobile"]),
                             ("first_mana_decrease",prev and sample["mana"] < prev["mana"]),
                             ("first_health_decrease",prev and sample["health"] < prev["health"])):
        if condition and label not in row["examples"]:
            row["examples"][label] = example
    for b in range(21,35):
        if mask & (1 << (b-21)):
            row["active_counts"][b] += 1
    for key in ("health", "shields", "mana", "t"):
        value = sample[key]
        lo, hi = row["ranges"].get(key,(value,value))
        row["ranges"][key] = [min(lo,value),max(hi,value)]
    prev = row["previous"]
    if prev and (sample["thing"],sample["guid"]) == (prev["thing"],prev["guid"]):
        for key in ("mana","health"):
            row[key+"_decreases"] += sample[key] < prev[key]
    row["previous"] = sample


def seat_schedule(jan_first):
    """Keep each profile's environment index while changing its place in the join queue."""
    seats = tuple(enumerate(LABELS.items()))
    return seats[::-1] if jan_first else seats


def run(args, receipt, tmp):
    schedule = seat_schedule(args.jan_first)
    repo, source, output = args.repo.resolve(), args.data.resolve(), args.output.resolve()
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(repo))
    from bots.run import prepare_bot, load_profiles, bot_environment
    from bots.settings import write_behavior
    from manager import config
    from manager.content import archive_index, catalog

    def git(*words):
        return subprocess.check_output(["git","-C",str(repo),*words],stderr=subprocess.DEVNULL,
                                       timeout=5,text=True).strip()
    if args.arena_baseline:
        interfaces = sorted(name for _, name in socket.if_nameindex())
        if interfaces != ["lo"]:
            raise Failure("arena_baseline_requires_isolated_loopback_network_namespace")
        receipt.update(kind="adjoin-arena-native-duel", network_interfaces=interfaces,
                       pacing="normal engine wall-clock", seed_control="not assigned or observed",
                       seat_order=[profile for _, (_, profile) in schedule], launcher_sha256=digest(Path(__file__)))
        paths = ("bots/profiles.json", "bots/run.py", "bots/companion.py", "bots/settings.py", "manager/config.py",
                 "manager/content.py", "native/BOT_BUILD.json", "qa/bots-stock-map-audit.json")
        if args.recorder:
            paths += ("web_gateway/ipc.py", "manager/spectator.py", "manager/spectator_geometry.py")
            receipt["recorder_sha256"] = digest(Path(args.recorder.__file__))
        receipt["launcher_input_sha256"] = {name: digest(repo / name) for name in paths}
    else:
        receipt.update(commit=git("rev-parse","HEAD"), branch=git("rev-parse","--abbrev-ref","HEAD"),
                       source_tree_clean=not bool(git("status","--porcelain","--untracked-files=no")))
    receipt.update(platform={"python":platform.python_version(),"glibc":platform.libc_ver()[1]},
                   render_environment=FLAGS, bot_options={"taunts":False,"team":0,
                       "force_style":"competitive","trace_force":True})
    bot, server = repo / BOT, repo / SERVER
    packaged = json.loads((repo/"native/BOT_BUILD.json").read_text())
    files = [BOT,str(Path(BOT).parent/GNS),PATCH,SERVER,str(Path(SERVER).parent/GNS)]
    hashes = receipt["sha256"] = {name:digest(repo/name) for name in files}
    if any(hashes[name] != packaged["files"][name]["sha256"] for name in files[:3]):
        raise Failure("packaged_bot_binary_patch_or_gns_hash_mismatch")
    if args.planner_client:
        bot, build = research_client(repo, args.planner_client, packaged, hashes)
        receipt["planner_experiment"] = {"mode": args.planner_quarantine, "build": build}
    if args.pace_build:
        import native_observation_pace as pace_tools
        server, bot, pace_build = pace_tools.resolve_build(repo, args.pace_build.resolve(), hashes, digest)
        build = pace_build["bot"]
        if args.red_policy_build:
            import native_red_match as red_tools
            bot, build = red_tools.resolve_client(repo, args.red_policy_build.resolve(), pace_build, digest,
                                                  transfer=bool(args.transfer_build), custom=bool(args.custom_build),
                                                  platform_build=bool(args.platform_build), hint_build=bool(args.hint_build),
                                                  competitive=bool(args.competitive_build))
            args.red_tools = red_tools
            receipt["kind"] = "adjoin-arena-stock-red-policy"
            receipt["red_policy"] = {"build":build, "elite":True, "model_side":args.model_side,
                                     "weights_sha256":digest(args.policy_weights) if args.policy_weights else None,
                                     "verifier_sha256":digest(Path(red_tools.__file__))}
        else:
            receipt["planner_experiment"] = {"mode": "on", "build": build}
        receipt["pacing"] = "native pace experiment"
        receipt["pace_experiment"] = {"speed": args.pace_rate, "requested_game_seconds": args.duration,
                                      "trace": "pace-trace.jsonl", "build": pace_build,
                                      "verifier_sha256": digest(Path(pace_tools.__file__))}
    server_dir = tmp/"server"
    stage(source,server_dir,stock_episode=not args.transfer_build)
    gob = server_dir/"episode/jk1mp.gob"
    for p in (server_dir/"resource").glob("*.gob"):
        hashes[p.name] = digest(p)
    map_key = "jkl/" + args.map
    if args.transfer_build:
        import native_mode_transfer as transfer
        args.transfer = transfer
        gob, asset = transfer.stage_episode(args, server_dir, archive_index, catalog, digest)
        hashes[gob.name] = asset["episode_sha256"]
        hashes[map_key] = asset["map_sha256"]
        policy = transfer.selection(args, hashes[map_key])
        if policy["controller"] == "learned":
            args.model_side = args.registry_side or args.model_side
            args.policy_weights = Path(policy["path"])
        receipt["kind"] = "adjoin-arena-mode-transfer"
        receipt["mode_transfer"] = {"content":asset,"mode":args.mode,"weapons":args.weapons,"force":args.force,
                                    "policy_selection":{k:v for k,v in policy.items() if k!="path"},
                                    "registry_side":args.registry_side}
        if args.custom_build:
            receipt["mode_transfer"]["custom_admission"] = transfer.custom_environment(asset, args.mode)
        if args.platform_build:
            receipt["mode_transfer"]["mesh_support"] = True
        if args.hint_build:
            hint_path = tmp / "active-route.hint"
            receipt["mode_transfer"]["route_hint"] = transfer.stage_route_hint(args, asset, hint_path)
        receipt["red_policy"].update(model_side=args.model_side,weights_sha256=policy["sha256"])
    else:
        hashes["jk1mp.gob"] = digest(gob)
        if hashes["jk1mp.gob"] != STOCK_MP:
            raise Failure("stock_episode_hash_mismatch")
        audit = json.loads((repo / "qa/bots-stock-map-audit.json").read_text())
        episode = next(item for item in audit["episodes"] if item["episode"] == "jk1mp")
        expected_hash = next(item["sha256"] for item in episode["maps"] if item["map"] == args.map)
        entry = next(item for item in archive_index(gob) if item["name"].casefold() == map_key)
        with gob.open("rb") as inp:
            inp.seek(entry["offset"])
            hashes[map_key] = hashlib.sha256(inp.read(entry["size"])).hexdigest()
        if hashes[map_key] != expected_hash:
            raise Failure("stock_map_hash_mismatch")
    if args.controlled_opening or args.ready_gate:
        # Build only in the clean private stage, before peers copy their data.
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        import controlled_opening
        variant = gob.with_name("controlled-opening.gob")
        receipt["opening_fixture"] = controlled_opening.build(
            gob, variant, ready_gate=args.ready_gate, swap_starts=args.swap_starts,
            observe_repeater=args.observe_repeater)
        variant.replace(gob)
        hashes["jk1mp.gob"] = digest(gob)
        hashes[map_key] = receipt["opening_fixture"]["variant_jkl_sha256"]
        receipt["kind"] = "adjoin-arena-controlled-opening"
        args.opening = controlled_opening
        if args.ready_gate:
            import ready_gate
            args.gate_verifier = ready_gate
            receipt["kind"] = "adjoin-arena-ready-gate"
            receipt["ready_gate_source_sha256"] = {
                module: digest(Path(source.__file__)) for module, source in
                (("controlled_opening.py", controlled_opening), ("ready_gate.py", ready_gate))}
    with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as sock:
        sock.bind(("127.0.0.1",0))
        port = sock.getsockname()[1]
    cfg = dict(config.DEFAULT,map=args.map,rank=8,native_port=port,bots_fists_peace=False,bots_force_enabled=True,
               bots_sabers_only=False,bots_taunts=False,web_enabled=False,spectator_rendering=False,
               name="Native Force QA",max_players=4)
    if args.transfer_build:
        cfg.update(episode=asset["episode"],teams=args.mode!="ffa",game_flags=0x100 if args.mode=="tdm" else 0,
                   rank=8 if args.force=="on" else 0,bots_force_enabled=args.force=="on",bots_sabers_only=args.weapons=="sabers")
        receipt["bot_options"]["requested_teams"] = {"dark":1,"light":2} if cfg["teams"] else {"dark":0,"light":0}
        receipt["bot_options"].pop("team")
    registry = config.registry(cfg)
    receipt["server_registry"] = registry.copy()
    receipt["server_registry"].pop("serverPassword")
    receipt["server_argv"] = ["-headless","-dedicatedServer","-episode",cfg["episode"],"-map",args.map]
    (server_dir/"registry.json").write_text(dump(registry))
    (server_dir/"player").mkdir()
    write_behavior(tmp/"behavior.cfg",cfg)
    profiles = load_profiles()
    receipt["bots"] = bots = {s:new_stats(s) for s in LABELS}
    if args.transfer_build:
        for owner in bots.values():
            owner["expected_rank"]=cfg["rank"]
    if args.competitive_build:
        receipt["competitive_controls"] = {"saber_tracking": args.saber_tracking, "light_loadout": args.light_loadout,
                                          "force_controller": "competitive"}
        bots["light"]["expected_style"] = args.light_loadout
    for side, pid in LABELS.items():
        if (profiles[pid]["force_side"],profiles[pid]["force_style"]) != (side,"competitive"):
            raise Failure(side+"_incorrect_profile")
        prepare_bot(server_dir,tmp/side,profiles[pid])
    host_env = private_env(server_dir, server)
    if args.pace_build:
        host_env.update(ADJOIN_PACE_ROLE="host", ADJOIN_PACE_RATE=str(args.pace_rate))
    boot("server",[str(server),*receipt["server_argv"]],server_dir,host_env,
         output, recorder=args.recorder, repo=repo, camera=args.camera, line_buffered=args.ready_gate or args.red_policy_build)
    before = time.monotonic()
    while not owns_udp(CHILDREN["server"].pid,port):
        check_liveness()
        if time.monotonic()-before > (60 if args.red_policy_build else 25):
            raise Failure("dedicated_server_udp_readiness_timeout")
        time.sleep(.1)
    receipt["dedicated_server_owned_udp_port"] = True
    partial = {s:b"" for s in LABELS}
    if args.pace_build:
        partial["server"] = b""

    def collect(trace):
        for side in partial:
            if side not in READERS:
                continue
            raw = partial[side] + READERS[side].read(1024*1024)
            lines = raw.split(b"\n")
            partial[side] = lines.pop()[-16384:]
            for line in lines:
                text = line.decode("ascii","replace").strip()
                if args.pace_build:
                    pace.observe("host" if side == "server" else side, CHILDREN[side].pid, text)
                if side == "server":
                    continue
                marker = text.find("BOT_")
                if marker >= 0:
                    observe(side,profiles[LABELS[side]]["name"],text[marker:],bots[side],trace)

    pace_file = (output/"pace-trace.jsonl").open("x", encoding="ascii", buffering=1) if args.pace_build else nullcontext()
    with pace_file as clock_trace, (output/"force-trace.jsonl").open("x",encoding="ascii",buffering=1) as trace:
        if args.pace_build:
            pace = pace_tools.NativePace(clock_trace, receipt["pace_experiment"], ungated=bool(args.red_policy_build))
        for index, (side, pid) in schedule:
            p = profiles[pid]
            directory = tmp/side
            env = private_env(directory,bot)
            standard = bot_environment(bot,directory,tmp,index,"",False,behavior_file=tmp/"behavior.cfg",
                                       team=(index+1 if cfg["teams"] else 0),force_side=side,
                                       force_style=bots[side].get("expected_style","competitive"))
            env.update({k:v for k,v in standard.items() if k.startswith("JK_BOT_")})
            env["JK_BOT_TRACE_FORCE"] = "1"
            if args.competitive_build:
                env["JK_BOT_SABER_TRACK"] = "1" if args.saber_tracking in ("both", side) else "0"
                if side == "light" and args.light_loadout == "master":
                    env["ADJOIN_LIGHT_LOADOUT_TRIAL"] = "1"
            if args.planner_quarantine:
                env["JK_BOT_PLANNER_QUARANTINE"] = "1" if args.planner_quarantine == "on" else "0"
            if args.pace_build:
                env.update(ADJOIN_PACE_ROLE=side, ADJOIN_PACE_RATE=str(args.pace_rate))
            if args.brain_trace:
                env["JK_BOT_TRACE_DECISIONS"] = "1"
            if args.brain_edge_model:
                brain_sha = digest(args.brain_edge_model.resolve())
                env.update(JK_BOT_EDGE_MODEL=str(args.brain_edge_model.resolve()),
                           JK_BOT_EDGE_MODEL_SHA256=brain_sha,
                           ADJOIN_EDGE_MODEL=str(args.brain_edge_model.resolve()),
                           ADJOIN_EDGE_MODEL_SHA256=brain_sha)
            if args.red_policy_build:
                env["ADJOIN_RED_TRACE"] = "1"
                env["JK_BOT_ELITE"] = "1"
                if args.transfer_build:
                    cache=transfer.cache_directory(args.nav_cache, pid, repo, source, output)
                    env["ADJOIN_NAV_CACHE"]=str(cache)
                    env.update(receipt["mode_transfer"].get("custom_admission", {}))
                    if args.hint_build:
                        env.update(ADJOIN_ROUTE_HINT=str(hint_path),
                                   ADJOIN_ROUTE_HINT_SHA256=receipt["mode_transfer"]["route_hint"]["sha256"])
                if side == args.model_side:
                    env.update(ADJOIN_RED_MODEL=str(args.policy_weights.resolve()),
                               ADJOIN_RED_MODEL_SHA256=receipt["red_policy"]["weights_sha256"])
                    if args.transfer_build:
                        env.update(ADJOIN_RED_MODEL_SCOPE=f"{args.mode}/{args.weapons}/"+("force" if args.force=="on" else "noforce"),
                                   ADJOIN_RED_MODEL_MAP_SHA256=hashes[map_key])
            args_bot = ["-headless","-botConnect",f"127.0.0.1:{port}","-botName",p["name"],
                        "-botSkin",p["model"],"-botSound",p["sound"]]
            bots[side]["argv"] = args_bot
            # Native COG diagnostics use stdout. Flush each line before shutdown.
            boot(side,[str(bot),*args_bot],directory,env,output,
                 line_buffered=args.controlled_opening or args.ready_gate or args.red_policy_build)
            # Give each real client its own discovery / welcome cycle before the next.
            wait_start = time.monotonic()
            while not bots[side]["joined"]:
                collect(trace)
                check_liveness()
                if time.monotonic()-wait_start>40:
                    raise Failure(side+"_join_timeout")
                time.sleep(.10)
        start_match = time.monotonic()
        if args.planner_quarantine or args.red_policy_build:
            images = {}
            if args.planner_quarantine:
                receipt["planner_experiment"]["loaded_images"] = images
            server_lib = str(Path(SERVER).parent / GNS)
            for label in ("server", *LABELS):
                proc = Path("/proc") / str(CHILDREN[label].pid)
                if label == "server":
                    expected_host = pace_build["host"]["binary_sha256"] if args.pace_build else hashes[SERVER]
                    images[label] = loaded_images(proc, server, expected_host, hashes[server_lib])
                else:
                    images[label] = loaded_images(proc, bot, build["binary_sha256"], build["gns_sha256"])
            if args.pace_build:
                receipt["pace_experiment"]["loaded_images"] = {
                    ("host" if label == "server" else label): {"pid": CHILDREN[label].pid, **image}
                    for label, image in images.items()}
        while True:
            collect(trace)
            check_liveness()
            cutoff = time.monotonic()
            if args.pace_build:
                cutoff_ns = time.monotonic_ns()
                done = pace.poll(cutoff_ns)
                # Uncapped (rate 0) has no scheduled speed; allow the 1x budget.
                watchdog = 12 + 2 * args.duration / (args.pace_rate or 1)
                if not done and cutoff - start_match > watchdog:
                    raise Failure("native_pace_game_window_watchdog")
                if done:
                    pace.finish(cutoff_ns)
            else:
                done = cutoff-start_match >= args.duration
            if done:
                receipt["both_joined_cutoff_monotonic"] = cutoff
                break
            time.sleep(.015 if args.pace_build else .15)
    receipt["both_joined_observation_wall_seconds"] = round(cutoff-start_match,2)
    for side, row in bots.items():
        if not row["joined"] or not row["loadout"] or row["matching_star_samples"] == 0:
            raise Failure(side+"_join_or_live_loadout_unverified")
        desired = {"sabers_only":int(cfg["bots_sabers_only"]),"fists_peace":0,"force_enabled":int(cfg["bots_force_enabled"])}
        if args.red_policy_build and row["behavior"] is None:
            # Red prints BOT_BEHAVIOR only on change. Its pinned startup values
            # already match this complete, read-only match configuration.
            expected_file = "version=1\nsabers_only=0\nfists_peace=0\nforce_enabled=1\n"
            if (tmp/"behavior.cfg").read_text("ascii") != expected_file:
                raise Failure(side+"_red_behavior_file_unverified")
            row["behavior"] = desired.copy()
            row["behavior_evidence"] = {"source":"pinned Red startup defaults and unchanged behavior file",
                                        "file_sha256":digest(tmp/"behavior.cfg")}
        if row["behavior"] != desired:
            raise Failure(side+"_behavior_unverified")
    if any(bots["light"]["joined"][k] == bots["dark"]["joined"][k] for k in ("slot","net")):
        raise Failure("duplicate_live_identity")
    receipt["effects"] = {"any_active_bin_sample":any(r["active_counts"] for r in bots.values()),
                          "any_mana_decrease":any(r["mana_decreases"] for r in bots.values()),
                          "any_immobile_sample":any(r["immobile_samples"] for r in bots.values()),
                          "any_health_decrease":any(r["health_decreases"] for r in bots.values()),
                          "target_effect_caster_attribution":"unverified"}
    receipt["status"] = "live_join_and_loadout_verified"


def finish_match(recorder, receipt, out, *, preserve_error):
    """End native gameplay before encoding. Preserve the original match error on dual failures."""
    if recorder:
        receipt["match_status"] = receipt["status"]
        recorder.stop_capture()
    cutoff = time.monotonic()
    if "both_joined_cutoff_monotonic" in receipt:
        receipt["cutoff_to_shutdown_request_seconds"] = round(cutoff - receipt["both_joined_cutoff_monotonic"], 6)
    try:
        shutdown()
    except Exception as error:
        receipt["shutdown_error"] = type(error).__name__
        if not preserve_error:
            raise
        return
    receipt["native_shutdown_wall_seconds"] = round(time.monotonic() - cutoff, 3)
    if not recorder:
        return
    flush_started = time.monotonic()
    try:
        evidence = recorder.finish()
        if evidence:
            receipt["observer_status"] = evidence["status"]
            receipt["observer_receipt"] = "spectator/observer-receipt.json"
            receipt["observer_receipt_sha256"] = evidence["receipt_sha256"]
    except Exception as error:
        receipt["observer_status"] = "failed"
        receipt["observer_error"] = type(error).__name__
        detail = out / "spectator/observer-receipt.json"
        if detail.is_file():
            receipt["observer_receipt"] = "spectator/observer-receipt.json"
            receipt["observer_receipt_sha256"] = hashlib.sha256(detail.read_bytes()).hexdigest()
        if not preserve_error:
            raise
    finally:
        receipt["observer_flush_wall_seconds"] = round(time.monotonic() - flush_started, 3)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("repo","data","output"):
        parser.add_argument("--"+key,type=Path,required=True)
    parser.add_argument("--map", default="m2.jkl")
    parser.add_argument("--duration",type=int,default=75,choices=range(1,3601),metavar="1..3600")
    parser.add_argument("--arena-baseline", action="store_true",
                        help="Require a private loopback-only network namespace and hash the tested inputs.")
    parser.add_argument("--record", action="store_true",
                        help="Capture the native host follow camera during an arena baseline.")
    scenario = parser.add_mutually_exclusive_group()
    scenario.add_argument("--ready-gate", action="store_true",
                          help="Hold both Canyon Oasis opening poses until both bot seats report ready.")
    scenario.add_argument("--controlled-opening", action="store_true",
                        help="Use a private Canyon Oasis variant to set each bot's first spawn and observe rifle inventory.")
    parser.add_argument("--jan-first", action="store_true",
                        help="Join Jan before Boba while retaining their profiles and the physical starts.")
    parser.add_argument("--swap-starts", action="store_true",
                        help="Exchange the two physical ready-gate starts, retaining bot seats and profiles.")
    parser.add_argument("--observe-repeater", action="store_true",
                        help="Sample the ready-gate owners' repeater inventory across lives.")
    parser.add_argument("--planner-client", type=Path, metavar="RESEARCH_BINARY",
                        help="Use the pinned planner experiment client and its adjacent networking library.")
    parser.add_argument("--planner-quarantine", choices=("off", "on"),
                        help="Run the research client in the matched control or shared-GO condition.")
    parser.add_argument("--pace-build", type=Path, metavar="DIRECTORY",
                        help="Use a verified native pace-build directory containing the paired host and planner client.")
    parser.add_argument("--pace-rate", type=int, choices=(0, 1, 2, 4, 8, 16, 32),
                        help="Set both players and host to the selected game speed (0=uncapped); --duration means game seconds.")
    parser.add_argument("--red-policy-build", type=Path, metavar="DIRECTORY",
                        help="Play an ungated stock match with the pinned native Red decision client.")
    parser.add_argument("--brain-trace", action="store_true",
                        help="Emit BOT_DECISION goal/weapon/Force lines for BrainStore ingestion.")
    parser.add_argument("--brain-edge-model", type=Path, metavar="FILE",
                        help="Frozen ADJOIN_EDGE_V1 artifact; its SHA-256 is passed to both bots.")
    parser.add_argument("--transfer-build", type=Path, metavar="DIRECTORY",
                        help="Use the pinned map- and mode-aware research client for an ungated match.")
    parser.add_argument("--custom-build", type=Path, metavar="DIRECTORY",
                        help="Use the separately pinned client that admits a locally verified custom episode.")
    parser.add_argument("--platform-build", type=Path, metavar="DIRECTORY",
                        help="Use the pinned custom client that recognizes supported walking surfaces over pits.")
    parser.add_argument("--hint-build", type=Path, metavar="DIRECTORY",
                        help="Use the pinned platform client with explicit map-scoped route hints.")
    parser.add_argument("--route-hint", type=Path, help="A local RED_ROUTE_HINT_V1 file.")
    parser.add_argument("--route-hint-sha256", help="Expected SHA-256 of the entire route file.")
    parser.add_argument("--route-hint-scope", help="The intended mode, weapons and Force preset, e.g. ffa/guns/force.")
    parser.add_argument("--mode", choices=("ffa","tdm","ctf"))
    parser.add_argument("--competitive-build", type=Path, help="Pinned stock-mode research client with saber tracking.")
    parser.add_argument("--saber-tracking", choices=("both", "neither", "dark", "light"), default="both",
                        help="Enable the new saber steering for the selected owner(s).")
    parser.add_argument("--light-loadout", choices=("competitive", "master"), default="competitive",
                        help="Compare a legal Light rank-eight master allocation using the same Force controller.")
    parser.add_argument("--weapons", choices=("guns","sabers"))
    parser.add_argument("--force", choices=("on","off"))
    parser.add_argument("--episode-file", type=Path)
    parser.add_argument("--episode-sha256")
    parser.add_argument("--map-sha256")
    parser.add_argument("--nav-cache", type=Path, help="Existing private external cache root shared across matches.")
    parser.add_argument("--policy-registry", type=Path)
    parser.add_argument("--registry-side", choices=("dark","light"))
    parser.add_argument("--trial-scope", help="Explicit candidate experiment scope, e.g. tdm/guns/noforce.")
    parser.add_argument("--trial-map-sha256")
    parser.add_argument("--trial-weights-sha256")
    parser.add_argument("--model-side", choices=("dark", "light"),
                        help="Apply a frozen decision model on this owner in an ungated Red policy match.")
    parser.add_argument("--policy-weights", type=Path, help="Frozen decision weights for --model-side.")
    parser.add_argument("--camera", choices=("follow", "rifle-overlook"),
                        help="Record the selected native camera (implies --record).")
    args = parser.parse_args()
    if args.competitive_build:
        if any((args.hint_build, args.custom_build, args.platform_build, args.transfer_build)):
            parser.error("--competitive-build selects a single stock-mode client")
        args.transfer_build = args.competitive_build
    elif args.saber_tracking != "both" or args.light_loadout != "competitive":
        parser.error("alternate saber controls and Light loadout require --competitive-build")
    if args.light_loadout == "master" and args.force != "on":
        parser.error("--light-loadout master requires a full Force match")
    hint = (args.route_hint, args.route_hint_sha256, args.route_hint_scope)
    if args.hint_build:
        if args.platform_build or args.custom_build or args.transfer_build or not all(hint):
            parser.error("--hint-build requires one route file, its SHA-256 and its exact scope")
        args.platform_build = args.hint_build
    elif any(hint):
        parser.error("route hint settings require --hint-build")
    if args.platform_build:
        if args.custom_build or args.transfer_build:
            parser.error("select a single transfer, custom, or platform build")
        args.custom_build = args.platform_build
    if args.custom_build:
        if args.transfer_build:
            parser.error("select one of --custom-build and --transfer-build")
        args.transfer_build = args.custom_build
    transfer_settings=(args.mode,args.weapons,args.force,args.episode_file,args.episode_sha256,args.map_sha256,args.nav_cache)
    trial = (args.trial_scope,args.trial_map_sha256,args.trial_weights_sha256)
    if args.transfer_build:
        if (not all(transfer_settings) or args.red_policy_build or (args.policy_registry is None) != (args.registry_side is None)
                or (any(trial) or args.model_side or args.policy_weights) and
                (not all(trial) or not args.model_side or not args.policy_weights or args.policy_registry)):
            parser.error("--transfer-build requires complete rules, episode/map pins and --nav-cache; "
                         "optional --policy-registry and --registry-side must be supplied together")
        args.red_policy_build=args.transfer_build
    elif (any(transfer_settings) or any(trial) or args.policy_registry or args.registry_side or args.map not in STOCK_MAPS):
        parser.error("custom maps, additional mode settings and registry selection require --transfer-build")
    if ((args.model_side is None) != (args.policy_weights is None) or args.model_side and not args.red_policy_build):
        parser.error("--model-side and --policy-weights require each other and --red-policy-build")
    if args.red_policy_build and (not args.arena_baseline or not args.pace_build or args.ready_gate
            or args.controlled_opening or args.observe_repeater or args.planner_quarantine or args.planner_client):
        parser.error("--red-policy-build requires a paced arena baseline with ordinary stock spawns")
    if ((args.pace_build is None) != (args.pace_rate is None)
            or args.pace_build and (args.planner_client or args.planner_quarantine
                                    or not args.red_policy_build and not (args.arena_baseline and args.ready_gate and args.observe_repeater))):
        parser.error("--pace-build and --pace-rate require each other and an instrumented arena ready gate; "
                     "the pace build already includes the shared-GO planner")
    if ((args.planner_client is None) != (args.planner_quarantine is None)
            or args.planner_client is not None and not (args.arena_baseline and args.ready_gate and args.observe_repeater)):
        parser.error("--planner-client and --planner-quarantine require each other, --arena-baseline, "
                     "--ready-gate and --observe-repeater")
    if args.pace_build and not args.red_policy_build:
        args.planner_quarantine = "on"
    if args.jan_first and not (args.ready_gate or args.red_policy_build):
        parser.error("--jan-first requires --ready-gate or --red-policy-build")
    if (args.swap_starts or args.observe_repeater) and not args.ready_gate:
        parser.error("--swap-starts and --observe-repeater are available only with --ready-gate")
    if args.camera:
        args.record = True
    else:
        args.camera = "follow"
    if args.camera == "rifle-overlook" and args.map != "m10.jkl":
        parser.error("--camera rifle-overlook requires Canyon Oasis (--map m10.jkl)")
    if (args.controlled_opening or args.ready_gate) and (not args.arena_baseline or args.map != "m10.jkl"):
        option = "--ready-gate" if args.ready_gate else "--controlled-opening"
        parser.error(f"{option} requires --arena-baseline and --map m10.jkl")
    if args.record and not args.arena_baseline:
        parser.error("--record requires --arena-baseline")
    args.recorder = None
    if args.record:
        import record_server
        args.recorder = record_server
    os.umask(0o077)
    for sig in (signal.SIGTERM,signal.SIGINT,signal.SIGHUP):
        signal.signal(sig,lambda num,frame:STOP.append(num))
    receipt = {"version":1,"requested_map":args.map,"requested_match_seconds":args.duration,"status":"failed"}
    made_output = False
    code = 1
    try:
        out = args.output.resolve()
        for inp in (args.data.resolve(),args.repo.resolve()):
            if inp == out or inp in out.parents or out in inp.parents:
                raise Failure("output_overlaps_inputs")
        out.mkdir(mode=0o700)
        made_output = True
        with tempfile.TemporaryDirectory(prefix="jk-force-",dir="/tmp") as temp:
            try:
                run(args,receipt,Path(temp))
            finally:
                finish_match(args.recorder, receipt, out, preserve_error=sys.exc_info()[0] is not None)
        if args.red_policy_build:
            receipt["red_policy"]["start_and_outcomes"] = args.red_tools.first_controls(out, receipt)
        if args.transfer_build:
            observed=receipt["mode_transfer"]["native"]=args.transfer.read_native(out,receipt)
            if observed["qualification_errors"]:
                raise Failure("native_transfer_rules_or_navigation_unverified")
        if args.controlled_opening or args.ready_gate:
            try:
                receipt["opening_observations"] = args.opening.qualify(
                    out, receipt["bots"], swap_starts=args.swap_starts, jan_first=args.jan_first)
            except (KeyError, IndexError, TypeError, ValueError) as error:
                raise Failure("controlled_opening_observations_failed") from error
        if args.ready_gate:
            try:
                receipt["ready_gate_observations"] = gate = args.gate_verifier.qualify(
                    out, receipt["opening_observations"], planner_mode=args.planner_quarantine)
                if args.planner_quarantine:
                    receipt["planner_experiment"]["owners"] = {side: gate["owners"][side]["planner"] for side in LABELS}
            except ValueError as error:
                receipt["ready_gate_error"] = str(error)
                raise Failure("ready_gate_observations_failed") from error
        if args.observe_repeater:
            try:
                receipt["repeater_observations"] = args.opening.qualify_repeater(
                    out, receipt["opening_observations"], receipt["ready_gate_observations"], jan_first=args.jan_first)
            except (IndexError, KeyError, TypeError, ValueError) as error:
                raise Failure("repeater_observations_failed") from error
        code = 0
    except Failure as e:
        receipt["error"] = str(e)
    except ValueError as e:
        receipt["error"] = str(e) if args.pace_build and re.fullmatch(r"native_(pace|red|transfer)_[a-z_]+", str(e)) else "ValueError"
    except Exception as e:
        # OSError strings often contain private installation paths.
        receipt["error"] = type(e).__name__
        if isinstance(e,OSError):
            receipt["errno"] = e.errno
        if isinstance(e,subprocess.CalledProcessError):
            receipt["exit_code"] = e.returncode
    if STOP:
        code = 1
        receipt["error"] = "interrupted_signal_%d" % STOP[0]
    if code:
        receipt["status"] = "failed"
    for row in receipt.get("bots",{}).values():
        row.pop("previous",None)
    if args.arena_baseline and made_output:
        pace_trace = args.output / "pace-trace.jsonl"
        if "pace_experiment" in receipt and pace_trace.is_file():
            with pace_trace.open("rb") as stream:
                receipt["pace_experiment"]["trace_sha256"] = hashlib.file_digest(stream, "sha256").hexdigest()
        receipt["log_sha256"] = {}
        for name in ("server.log","dark.log","light.log","force-trace.jsonl"):
            log = args.output / name
            if log.is_file():
                with log.open("rb") as stream:
                    receipt["log_sha256"][name] = hashlib.file_digest(stream, "sha256").hexdigest()
    receipt["elapsed_wall_seconds"] = round(time.monotonic()-START,2)
    if made_output:
        with (args.output/"receipt.json").open("x",encoding="ascii") as f:
            f.write(dump(receipt)+"\n")
    print(dump(receipt),flush=True)
    return code


if __name__ == "__main__":
    sys.exit(main())
