"""Verify custom-map admission, first-life horizontal movement and platform support from match logs."""
import argparse
from collections import Counter
import json
import math
from pathlib import Path
import re

from audit_transfer_navigation import digest, owner


def read_owner(path, receipt, side, content, scope, hint_sha=None):
    expected = {"status": "accepted", "mode": scope.split("/")[0], "episode": content["episode"],
                "map": content["map"], "gob_sha": content["episode_sha256"], "map_sha": content["map_sha256"]}
    pid = str(receipt["pace_experiment"]["loaded_images"][side]["pid"])
    if digest(path) != receipt["log_sha256"][path.name]:
        raise ValueError("Owner log digest mismatch")
    phases, positions, support = {}, {}, Counter()
    controls, first_pose, support_first = Counter(), None, None
    life = None
    hints, sequences, evidence, post_exit_sectors = Counter(), {}, [], set()
    exit_life = None
    for number,line in enumerate(path.read_text(errors="replace").splitlines(),1):
        tag, _, tail = line.partition(" ")
        v = dict(x.split("=",1) for x in tail.split() if "=" in x)
        if tag == "BOT_RED_CUSTOM":
            if any(v.get(k)!=val for k,val in expected.items()) or v.get("pid")!=pid:
                raise ValueError("Custom identity mismatch")
            phases.setdefault(v["phase"],number)
        if tag in ("BOT_RED_JOIN","BOT_RED_FIRST","BOT_RED_APPLY"):
            if v.get("pid")!=pid: raise ValueError("Unexpected owner process")
            phases.setdefault(tag,number)
            if tag=="BOT_RED_FIRST":
                life=int(v["life"])
        if life is None: continue
        if tag=="BOT_RED_NAV":
            controls["steering_samples"]+=1
            controls["nonzero_steering_samples"]+=float(v["fwd"])!=0 or float(v["slide"])!=0
            if life==exit_life:post_exit_sectors.add(int(v["sector"]))
        if tag=="BOT_RED_APPLY":
            controls["first_nonzero_apply_per_life"]+=float(v["fwd"])!=0 or float(v["slide"])!=0
        if tag=="BOT_PLATFORM_SUPPORT":
            key=(int(v["sector"]),int(v["fixture"]),int(v["exit_sector"]))
            support[key]+=1
            if support_first is None:
                support_first={k:v[k] for k in ("t","sector","fixture","next_fixture","pos","ahead","probes","void_rejects","exit_sector","fwd","slide")}
        if tag=="BOT_ROUTE_HINT":
            if v["pid"]!=pid or v["map_sha"]!=content["map_sha256"] or (hint_sha and v["hint_sha"]!=hint_sha):
                raise ValueError("Route hint identity mismatch")
            phase=v["phase"]
            hints[(phase,v["status"])]+=1
            if phase in ("start","arrive","exit"):
                evidence.append({k:v[k] for k in ("t","phase","status","life","seq","sector","fixture","pos")})
            if phase=="step":
                if float(v["fwd"])==0 and float(v["slide"])==0:raise ValueError("Hint claims unmoving step")
                sequences.setdefault(int(v["life"]),set()).add(int(v["seq"]))
            if phase=="exit":exit_life=life
        if tag not in ("BOT_STATUS","BOT_PLATFORM_SUPPORT","BOT_ROUTE_HINT"): continue
        xyz=tuple(map(float,v["pos"].split(",")))
        if len(xyz)!=3 or not all(map(math.isfinite,xyz)): raise ValueError("Invalid native position")
        if first_pose is None:first_pose={"time":float(v["t"]),"sector":int(v["sector"]),"xyz":xyz}
        group=positions.setdefault(life,dict(start=xyz,xy=0.0,z=0.0,samples=0))
        group["xy"]=max(group["xy"],math.dist(group["start"][:2],xyz[:2]))
        group["z"]=max(group["z"],abs(group["start"][2]-xyz[2]))
        group["samples"]+=1
    sequence=[phases[key] for key in ("admission","world","BOT_RED_FIRST")]
    if "BOT_RED_APPLY" in phases:sequence.append(phases["BOT_RED_APPLY"])
    if any(a>=b for a,b in zip(sequence,sequence[1:])): raise ValueError("Unexpected custom/control marker order")
    if hint_sha and hints["load","ready"]!=1: raise ValueError("Expected one ready route hint for this owner")
    result=owner(path,scope,content["map_sha256"])
    if result["map_hashes"]!=[content["map_sha256"]] or result["scopes"]!=[scope]:raise ValueError("Unexpected context")
    return dict(pid=int(pid),log_sha256=result["log_sha256"],phase_lines=phases,first_measured_pose=first_pose,
                max_within_life_xy=round(max((p["xy"] for p in positions.values()),default=0),4),
                max_within_life_abs_z=round(max((p["z"] for p in positions.values()),default=0),4),
                position_samples=sum(p["samples"] for p in positions.values()),controls=dict(controls),
                platform_counts=[dict(sector=k[0],fixture=k[1],exit_sector=k[2],samples=v) for k,v in sorted(support.items())],
                first_supported_step=support_first,sectors=result["sectors"],route=result["route"],
                gear_models=result["gear_models"],loaded_edges=result["loaded_edges"],
                hint_counts=[dict(phase=k[0],status=k[1],samples=v) for k,v in sorted(hints.items())],
                hint_driven_indices={k:sorted(v) for k,v in sequences.items()},hint_progress=evidence,
                sectors_observed_after_exit_same_life=sorted(post_exit_sectors))


def audit(args):
    schedule=json.loads(args.schedule.read_bytes())
    specs={r["name"]:r for r in schedule["matrix"]+schedule["unseen"]}
    runs=[]
    for target in args.case:
        key,separator,attempt=target.partition("=")
        attempt=attempt if separator else key
        if not re.fullmatch(r"[a-zA-Z0-9_-]+",attempt): raise ValueError("Invalid run directory")
        spec=specs[key]
        directory=args.runs/attempt
        receipt=directory/"receipt.json"
        data=json.loads(receipt.read_bytes())
        content=data["mode_transfer"]["content"]
        if content["map_sha256"]!=spec["map_sha256"] or content["map"]!=spec["map"]:
            raise ValueError("Map differs from schedule")
        scope="/".join((spec["mode"],"guns" if spec["weapons"]=="guns" else "sabers",
                        "force" if spec["force"]=="on" else "noforce"))
        runs.append(dict(schedule_id=key,attempt=attempt,receipt_sha256=digest(receipt),status=data["status"],
                         content={k:content[k] for k in ("episode","episode_sha256","map","map_sha256")},
                         owners={side:read_owner(directory/(side+".log"),data,side,content,scope,args.hint_sha256)
                                 for side in ("dark","light")}))
    return dict(schema=1,schedule_sha256=digest(args.schedule),analyzer_sha256=digest(Path(__file__)),attempts=runs)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs",required=True,type=Path)
    parser.add_argument("--schedule",required=True,type=Path)
    parser.add_argument("--output",required=True,type=Path)
    parser.add_argument("--case",required=True,action="append",metavar="SCHEDULE_ID[=ATTEMPT]")
    parser.add_argument("--hint-sha256",help="Require a ready native load of these route bytes on every selected owner.")
    args=parser.parse_args()
    args.output.write_text(json.dumps(audit(args),indent=2)+"\n",encoding="utf-8")
