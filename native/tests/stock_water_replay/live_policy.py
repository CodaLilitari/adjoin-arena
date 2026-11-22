"""Exercise real JKCP motor control and live policy replacement under stock physics.

This bounded integration probe uses owned map geometry, an identified native
fixture seat, loopback HTTP, separate policy processes and real engine input
handlers. It is not a rendered match or a competitive skill evaluation.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time

from collect_motor import case_environment
from run import HERE, build_replay

sys.path.insert(0,str(HERE.parents[2]))
from bots.companion import Hub
from bots.companion_cli import call, load_private


def source(turn):
    return '''ABI_VERSION = 1
def decide(observation, context):
    if context.get("undertaking"):
        return {"action":"wait"}
    sense = observation["lily"]["sense"]
    if sense["medium"] == "water" or not sense["supported"]:
        return {"action":"baseline"}
    return {"action":"motor", "skill":"physical-probe", "steps":[{
        "duration_ms":550, "forward":0.45, "turn":TURN}],
        "goal":{"direction":sense["facing"], "distance":0.015}}
'''.replace("TURN",repr(turn))


def replace(path, text):
    stage=path.with_suffix(".stage")
    stage.write_text(text,encoding="utf-8")
    stage.replace(path)


def trace_rows(path):
    if not path.exists():
        return []
    # The last line may be in flight; complete JSONL records alone are evidence.
    lines=path.read_text().splitlines(keepends=True)
    return [json.loads(line) for line in lines if line.endswith("\n")]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ("source","build","map","output"):
        parser.add_argument("--"+name,type=Path,required=True)
    args=parser.parse_args()
    args.output.mkdir(mode=0o700,parents=True,exist_ok=False)
    policy=args.output / "live_policy.py"
    trace=args.output / "controller.jsonl"
    first,second=source(.25),source(-.25)
    hashes=[hashlib.sha256(s.encode()).hexdigest() for s in (first,second)]
    replace(policy,first)
    row=next(csv.DictReader((HERE/"bank_cases.tsv").open(),delimiter="\t"))
    engine=controller=hub=None
    stop=threading.Event()
    pumping=None
    observations=[]
    edited=rejected_candidate=False
    with tempfile.TemporaryDirectory(prefix="lily-live-physics-") as tmp:
        executable,geometry,provenance=build_replay(args.source,args.build,args.map,Path(tmp))
        engine_log=(args.output / "engine.log").open("wb")
        controller_log=(args.output / "controller.log").open("wb")
        try:
            hub=Hub(args.output,["lily"],0,experimental_ids=("lily",))
            def pump():
                while not stop.wait(.005):
                    hub.pump()
            pumping=threading.Thread(target=pump,name="physical-probe-pump",daemon=True)
            pumping.start()
            child=hub.take_socket("lily")
            env=case_environment(row,0)
            env.update(JK_BOT_LILY="1",JK_BOT_COMPANION_FD=str(child.fileno()),
                       LILY_REPLAY_REALTIME="1",LILY_REPLAY_CONTINUE="1",LILY_REPLAY_SECONDS="30")
            engine=subprocess.Popen([executable,geometry,*[row[n] for n in
                ("origin","wet","dry","start_sector","control_dt")]],env=env,
                pass_fds=(child.fileno(),),stdout=engine_log,stderr=subprocess.STDOUT)
            child.close()
            credential=load_private(args.output/"companion/lily.json")
            controller=subprocess.Popen([sys.executable,"-B","-m","bots.lily",
                "--credentials",str(args.output/"companion/lily.json"),"--policy",str(policy),
                "--memory",str(args.output/"experience.sqlite3"),
                "--environment-id","stock-water-"+provenance["map_sha256"][:24],
                "--trace",str(trace),"--duration-seconds","26"],
                cwd=HERE.parents[2],stdout=controller_log,stderr=subprocess.STDOUT)
            deadline=time.monotonic()+35
            while engine.poll() is None and time.monotonic()<deadline:
                observed=call(credential,"observation")
                sense=(observed.get("lily") or {}).get("sense")
                if sense:
                    observations.append({"time":time.monotonic(),"sense":sense,
                                         "controller_running":controller.poll() is None})
                rows=trace_rows(trace)
                if not edited and sum(r.get("event")=="outcome" and r.get("policy_hash")==hashes[0] for r in rows)>=2:
                    replace(policy,second)
                    edited=True
                if edited and not rejected_candidate and sum(r.get("event")=="outcome" and r.get("policy_hash")==hashes[1] for r in rows)>=2:
                    replace(policy,"ABI_VERSION=1\nraise ValueError('deliberate invalid candidate')\n")
                    rejected_candidate=True
                time.sleep(.04)
            engine.wait(timeout=3)
            controller.wait(timeout=3)
        finally:
            for process in (controller,engine):
                if process and process.poll() is None:
                    process.terminate()
                    try: process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill(); process.wait()
            stop.set()
            if pumping: pumping.join(timeout=2)
            if hub: hub.close()
            engine_log.close();controller_log.close()
    rows=trace_rows(trace)
    outcomes=[r for r in rows if r.get("event")=="outcome"]
    applied={h:[r for r in rows if r.get("event")=="observation" and r.get("policy_hash")==h
                and r.get("episode_id") and r["sense"].get("owner")=="motor"] for h in hashes}
    checks={"engine_landed":engine.returncode==0,
        "controller_exited_cleanly":controller.returncode==0,
        "both_policies_activated":all(any(r.get("event")=="activated" and r.get("policy_hash")==h for r in rows) for h in hashes),
        "both_policies_applied_inputs":all(applied.values()),
        "invalid_candidate_rejected":any(r.get("event")=="rejected" for r in rows),
        "baseline_resumed_after_controller_stop":any(not o["controller_running"] and o["sense"]["owner"]=="baseline" for o in observations)}
    receipt={"schema":1,"probe":"stock-physics live JKCP motor control and executable replacement",
        "provenance":provenance,"policy_hashes":hashes,"checks":checks,
        "activated":[{k:r[k] for k in ("policy_hash","previous_hash","monotonic_seconds") if k in r} for r in rows if r["event"]=="activated"],
        "observed_motor_samples":{h:len(applied[h]) for h in hashes},
        "outcomes":[{k:r[k] for k in ("policy_hash","action_seq","status","physical_success","duration_seconds","applied_ms") if k in r} for r in outcomes],
        "limitations":["No rendering, multiplayer opponents, inventory COG execution or Force effects in this fixture.",
            "The two probe policies deliberately test control authority; they are not competitive candidates.",
            "A short observed displacement is distinct from successful water escape or improved game performance."]}
    (args.output/"receipt.json").write_text(json.dumps(receipt,indent=2)+"\n")
    print(json.dumps({"checks":checks,"motor_samples":receipt["observed_motor_samples"],"outcomes":len(outcomes)},indent=2))
    return 0 if all(checks.values()) else 1


if __name__=="__main__":
    raise SystemExit(main())
