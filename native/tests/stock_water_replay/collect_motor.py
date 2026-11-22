"""Collect private applied-control demonstrations from the bank replay matrix."""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

from run import HERE, build_replay, clean_environment


def case_environment(row, yaw):
    env = clean_environment()
    names = {"x":"X", "y":"Y", "z":"Z", "flags":"PF", "health":"HEALTH",
             "endurance_ms":"END", "pitch":"PITCH", "vertical_speed":"VZ"}
    env.update({"TRACE_"+key:row[name] for name,key in names.items()})
    env["TRACE_YAW"] = str(yaw)
    return env


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "build", "map"):
        parser.add_argument("--"+name, required=True, type=Path)
    parser.add_argument("--cases", type=Path, default=HERE / "bank_cases.tsv")
    parser.add_argument("--output", type=Path, required=True, help="New private output directory")
    args = parser.parse_args()
    args.output.mkdir(mode=0o700, parents=True, exist_ok=False)
    cases = list(csv.DictReader(args.cases.open(), delimiter="\t"))
    results = []
    with tempfile.TemporaryDirectory(prefix="lily-motor-collector-") as tmp:
        executable, geometry, provenance = build_replay(args.source, args.build, args.map, Path(tmp))
        for row in cases:
            if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}",row["case"]):
                raise ValueError("Invalid case identity")
            for yaw in row["yaw_offsets"].split(","):
                yaw = int(yaw)
                episode = row["case"]+"-yaw"+str(yaw)
                trace = args.output / (episode+".jsonl")
                log = args.output / (episode+".log")
                env = case_environment(row,yaw)
                env.update(LILY_MOTOR_TRACE=str(trace.resolve()), LILY_MOTOR_EPISODE=episode,
                           LILY_MOTOR_GROUP=row["case"],
                           LILY_MOTOR_POLICY=provenance["policy_hash"])
                command = [executable,geometry,*[row[n] for n in ("origin","wet","dry","start_sector","control_dt")]]
                with log.open("wb") as stream:
                    completed = subprocess.run(command,env=env,stdout=stream,stderr=subprocess.STDOUT,timeout=90)
                records = [json.loads(line) for line in trace.read_text().splitlines()] if trace.exists() else []
                terminal = records[-1] if records and records[-1].get("event")=="outcome" else {}
                if completed.returncode not in (0,1) or not terminal:
                    raise RuntimeError("Replay failed before a physical verdict: "+episode)
                results.append({"episode_id":episode,"returncode":completed.returncode,
                    "physical_success":terminal["physical_success"],"duration_seconds":terminal["duration_seconds"],
                    "samples":len(records)-1,"trace_sha256":hashlib.sha256(trace.read_bytes()).hexdigest()})
                print(json.dumps(results[-1]),flush=True)
    receipt = {"schema":1,"controller":"native-baseline", "provenance":provenance,
        "cases_sha256":hashlib.sha256(args.cases.read_bytes()).hexdigest(), "episodes":results,
        "limitations":["Stock world physics and input handling, simplified actor fixture; no rendered multiplayer match.",
            "Initial horizontal velocity is zero and the existing air-recovery timer is primed.",
            "Successful demonstrations support behavior cloning, not a claim of stronger gameplay."]}
    (args.output / "receipt.json").write_text(json.dumps(receipt,indent=2)+"\n")
    return 0 if all(r["physical_success"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
