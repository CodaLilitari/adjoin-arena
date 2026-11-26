#!/usr/bin/env python3
"""Replay controlled navigation challenges in the original stock maps, on a real loopback game."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tarfile
import time

HERE = Path(__file__).resolve().parent
NATIVE = HERE.parents[1]
REPO = NATIVE.parent
sys.path[:0] = [str(REPO), str(NATIVE), str(REPO / "scripts/bot_development/legacy")]
from build_arena_pace import link_file, read, sha
from bots.match_storage import match_scratch
from manager import config
from manager.content import archive_index, child_casefold
from native_force_observation import stage, private_env, owns_udp

CASES = {
    "concussion": ("m4.jkl", 13),
    "railgun": ("m4.jkl", 14),
    "rim": ("m4.jkl", 69),
    "nar": ("m2.jkl", 48),
}


def build(source, generated, out):
    """Relink only the test-owned controller and stock item observer."""
    archive = NATIVE / "competitive-relink-linux-x86_64.tar.gz"
    stock = read(NATIVE / "competitive-stock-build.json")
    if sha(archive) != stock["relink_sha256"]:
        raise ValueError("Research replay needs the matching competitive relink bundle")
    objects = out / "objects"
    objects.mkdir()
    with tarfile.open(archive) as members:
        members.extractall(objects, filter="data")

    controller = (source / "src/AI/jkBot.c").read_text()
    tick = "    Red_FinishDecision();"
    if controller.count(tick) != 1 or "Bot_GuardGround(self);" not in controller:
        raise ValueError("Expected the composed native competitive controller including navigation")
    cases = "\n".join((HERE / name).read_text() for name in ("shelf.inc", "lift_return.inc", "rim.inc"))
    probe = "    int scenario=atoi(getenv(\"ADJOIN_LIFT_REPLAY\") ?: \"0\");\n" + cases
    c = out / "controller.c"
    c.write_text('#include "World/sithThing.h"\n' + controller.replace(tick, probe + "\n" + tick))

    item = (source / "src/World/sithItem.c").read_text()
    taken = "sithCog_ThingSendMessage(pItem, pSrcThing, SITH_MESSAGE_TAKEN);"
    if item.count(taken) != 1:
        raise ValueError("Expected the stock local-player TAKEN dispatcher")
    before = r'''replayLastTaken=(int)(pItem-sithWorld_g_pCurrentWorld->aThings);
        fprintf(stderr,"REPLAY_TAKEN item=%d sec=%u\n",replayLastTaken,pSrcThing->sector->id);
        '''
    i = out / "stock_item.c"
    i.write_text('#include <stdio.h>\n#include "World/sithWorld.h"\nint replayLastTaken=-1;\n'
                 + item.replace(taken, before + taken))
    flags = read(NATIVE / "competitive-build.json")["flags"]
    for src, unit in ((c, "AI/jkBot"), (i, "World/sithItem")):
        args = ["cc", *flags, "-I" + str(source / "src"), "-I" + str((source / "src" / unit).parent),
                "-I" + str(generated), "-c", src, "-o", objects / f"CMakeFiles/sith_engine.dir/src/{unit}.c.o"]
        subprocess.run(args, check=True)
    subprocess.run(["cc", "-x", "c", "-c", "/dev/null", "-o", objects / "arena_pace.o"], check=True)
    libs = out / "libs"
    libs.mkdir()
    link_file.libs = subprocess.check_output(["/sbin/ldconfig", "-p"], text=True).splitlines()
    binary = out / "jk-bot-navigation-replay"
    shutil.copy2(link_file(read(objects / "link.json"), "bot", objects, libs), binary)
    shutil.copy2(objects / "GameNetworkingSockets/lib/libGameNetworkingSockets.so", binary.parent)
    return binary


def stock_map_digest(data, level):
    episode = child_casefold(data, "episode")
    archive = child_casefold(episode, "jk1mp.gob") if episode else None
    if not archive:
        raise ValueError("Missing stock JK1MP episode")
    entry = next((e for e in archive_index(archive) if Path(e["name"]).name.casefold() == level), None)
    if not entry or entry["size"] > 32 * 1024 * 1024:
        raise ValueError(f"Missing or oversized {level} in JK1MP")
    with archive.open("rb") as file:
        file.seek(entry["offset"])
        digest = hashlib.sha256(file.read(entry["size"])).hexdigest()
    audit = read(REPO / "qa/bots-stock-map-audit.json")
    expected = next(m["sha256"] for e in audit["episodes"] for m in e["maps"] if m["map"] == level)
    if digest != expected:
        raise ValueError(f"Controlled poses require the stock {level} geometry")
    return digest


def run(case, data, binary, out, scratch, veto_off, seconds):
    level, number = CASES[case]
    map_digest = stock_map_digest(data, level)
    server = scratch / case
    stage(data, server)
    (server / "player").mkdir()
    cfg = dict(config.DEFAULT, game_data=str(server), episode="JK1MP", map=level, rank=0,
               bots_sabers_only=False, bots_force_enabled=False, bots_taunts=False, web_enabled=False,
               spectator_rendering=False, engine_display="offscreen", max_players=5)
    cfg_file = out / "config.json"
    cfg_file.write_text(json.dumps(cfg))
    (server / "registry.json").write_text(json.dumps(config.registry(cfg)))
    engine = REPO / "bin/linux-x86_64/openjkdf2"
    with (out / "server.log").open("wb") as server_log, (out / "runner.log").open("wb") as runner_log:
        host = subprocess.Popen([engine, "-headless", "-dedicatedServer", "-episode", "JK1MP", "-map", level],
                                cwd=server, env=private_env(server, engine), stdout=server_log, stderr=subprocess.STDOUT)
        try:
            limit = time.monotonic() + 40
            while not owns_udp(host.pid, cfg["native_port"]):
                if host.poll() is not None or time.monotonic() > limit:
                    raise RuntimeError("Stock server did not open its port")
                time.sleep(0.1)
            env = dict(os.environ, HOME=str(out), LANG="C", ADJOIN_RED_TRACE="1", ADJOIN_LIFT_REPLAY=str(number))
            env.pop("ADJOIN_VETO_OFF", None)
            if veto_off:
                env["ADJOIN_VETO_OFF"] = "1"
            subprocess.run([sys.executable, "-B", "-m", "bots.run", "--server-config", cfg_file,
                            "--profiles", "jan_ors", "--runtime", out / "bots", "--engine", binary,
                            "--scratch-root", scratch, "--no-taunts", "--seconds", str(seconds)], cwd=REPO, env=env, stdout=runner_log,
                           stderr=subprocess.STDOUT, timeout=seconds + 65, check=True)
        finally:
            host.terminate()
            try:
                host.wait(timeout=6)
            except subprocess.TimeoutExpired:
                host.kill()
                host.wait()
    logs = list((out / "bots").glob("*/*/client.log"))
    if len(logs) != 1:
        raise ValueError("Expected one owner log")
    lines = logs[0].read_text(errors="replace").splitlines()
    markers = [line for line in lines if line.startswith(("REPLAY_TAKEN", "REPLAY_PICKUP", "REPLAY_ESCAPED",
               "REPLAY_SAFE_EXIT", "NAR_APPROACH", "NAR_RETURNED", "RIM_BEGIN", "RIM_END"))]
    def fields(line):
        return dict(x.split("=", 1) for x in line.split()[1:] if "=" in x)
    if case in ("concussion","railgun"):
        passed = all(any(l.startswith(f"{event} item={number} ") for l in markers) for event in
                     ("REPLAY_TAKEN","REPLAY_PICKUP","REPLAY_ESCAPED","REPLAY_SAFE_EXIT"))
    elif case=="nar":
        returned = [fields(l) for l in markers if l.startswith("NAR_RETURNED ")]
        passed = bool(returned and int(returned[0]["vetoes"])>0 and returned[0]["life"]==returned[0]["start_life"]
                      and float(returned[0]["hp_after"])>=float(returned[0]["hp_before"]))
    else:
        finished=[fields(l) for l in markers if l.startswith("RIM_END ")]
        passed=bool(finished and int(finished[0]["brakes"])>0 and float(finished[0]["min_z"])>1.84
                    and int(finished[0]["attach"])&1 and finished[0]["life"]==finished[0]["start_life"])
    result=dict(case=case, map_sha256=map_digest, disabled_comparison=veto_off, guard_criterion_passed=passed,
                bot_sha256=sha(binary), server_sha256=sha(engine), owner_log_sha256=sha(logs[0]), markers=markers)
    (out / "result.json").write_text(json.dumps(result, indent=2)+"\n")
    print(json.dumps(result),flush=True)
    return passed


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="Assembled native competitive engine source")
    parser.add_argument("--generated", type=Path, required=True, help="Directory containing matching globals.h")
    parser.add_argument("--data", type=Path, required=True, help="Installed retail game data")
    parser.add_argument("--out", type=Path, required=True, help="New directory outside any checkout")
    parser.add_argument("--scratch-root", type=Path, help="Temporary build and game data location (or ADJOIN_MATCH_SCRATCH)")
    parser.add_argument("--cases", choices=CASES, nargs="+", default=list(CASES))
    parser.add_argument("--veto-off", action="store_true", help="Hold the same rim or Nar approach with its final guard disabled")
    parser.add_argument("--seconds", type=int, default=30)
    args=parser.parse_args()
    if [name for _,name in socket.if_nameindex()]!=["lo"]:
        parser.error("Run in a loopback-only network namespace")
    if args.veto_off and any(c not in ("rim","nar") for c in args.cases):
        parser.error("--veto-off applies only to rim and nar")
    out=args.out.resolve()
    if out.exists() or any((p/".git").exists() for p in out.parents):
        parser.error("--out must be new and outside a checkout")
    out.mkdir(parents=True)
    with match_scratch(args.scratch_root, (args.data, args.source, out)) as scratch:
        binary=build(args.source.resolve(),args.generated.resolve(),scratch)
        ok=True
        for case in args.cases:
            dest=out/case
            dest.mkdir()
            with match_scratch(scratch, (args.data, out)) as case_scratch:
                ok=run(case,args.data.resolve(),binary,dest,case_scratch,args.veto_off,args.seconds) and ok
    return 0 if ok or args.veto_off else 1


if __name__=="__main__":
    raise SystemExit(main())
