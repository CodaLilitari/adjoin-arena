"""Read native flag, movement and route-learning evidence after a transfer run."""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re

CAPTURE={"Red Team Captured The Flag!":"red","Gold Team Captured The Flag!":"gold"}
PICKUP={"The Red Flag is yours!":"red","The Gold Flag is yours!":"gold"}


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream,"sha256").hexdigest()


def pair(text):
    a,b=text.split(",")
    return int(a),int(b)


def owner(path,scope,map_sha):
    contexts=[]; objectives=Counter(); reported=Counter(); model_counts=Counter()
    teams=set(); targets=set(); sectors=set(); flags=set(); carriers=set(); homes=set(); scores=[]
    start=None; max_displacement=0; positions=0; nodes=edges=arrivals=stalls=motion=0
    life_start=None; same_life_displacement=0; applications=0
    active=False; fresh_feedback=False; recall_before_feedback=reads=good_reads=0; ready=False
    decision=None; seen_reads=set(); loaded=[]; coverage=None; first_restore=None
    verified_capture=[]; flag_state=None; local_hud=Counter(); capture_hud=Counter()
    for line in path.read_text(errors="replace").splitlines():
        text=line.strip()
        if text in CAPTURE: capture_hud[CAPTURE[text]]+=1
        if text in PICKUP: local_hud[PICKUP[text]]+=1
        tag,sep,tail=line.partition(" ")
        if not sep or not tag.startswith("BOT_"): continue
        v=dict(part.split("=",1) for part in tail.split() if "=" in part)
        if tag=="BOT_RED_CONTEXT":
            active=v["scope"]==scope and v["map_sha"]==map_sha
            contexts.append((v["map_sha"],v["scope"],int(v["flags"],16),int(v["bindings"]),v["cache"],int(v["scope_match"])))
            if active: loaded.append(int(v["loaded_edges"]))
            decision=None
            continue
        if not active: continue
        if tag=="BOT_RED_FIRST":
            life_start=None
        elif tag=="BOT_RED_APPLY":
            applications+=abs(float(v["fwd"]))+abs(float(v["slide"]))>0
        elif tag=="BOT_RED_NAV":
            reported["samples"]+=1
            teams.add(int(v["team"])); targets.add(int(v["target_team"])); sectors.add(int(v["sector"]))
            nodes=max(nodes,int(v["nodes"])); edges=max(edges,int(v["edges"])); ready|=v["ready"]=="1"
            arrivals=max(arrivals,int(v["arrivals"])); stalls=max(stalls,int(v["stalls"]))
            motion+=abs(float(v["fwd"]))+abs(float(v["slide"]))>0
            if v["objective_valid"]=="1": objectives[v["objective"]]+=1
            home=pair(v["home"]); carrier=pair(v["carriers"])
            flags.add(pair(v["flags"])); carriers.add(carrier); homes.add(home)
            score=(int(v["red_score"]),int(v["gold_score"]))
            if not scores or scores[-1]!=score: scores.append(score)
            if flag_state:
                prior_home,prior_carrier,prior_score=flag_state
                for team,color in enumerate(("red","gold")):
                    enemy=1-team
                    if (prior_home[enemy]==0 and prior_carrier[enemy]>=0 and home[enemy]==1 and
                            carrier[enemy]==-1 and score[team]-prior_score[team]>=15):
                        verified_capture.append([float(v["t"]),color,score[team]-prior_score[team]])
            flag_state=(home,carrier,score)
        elif tag=="BOT_STATUS" and "pos" in v:
            pos=tuple(map(float,v["pos"].split(",")))
            if len(pos)!=3 or not all(map(math.isfinite,pos)): raise ValueError("invalid native position")
            if start is None: start=pos
            if life_start is None: life_start=pos
            max_displacement=max(max_displacement,math.dist(start,pos)); positions+=1
            same_life_displacement=max(same_life_displacement,math.dist(life_start,pos))
        elif tag=="BOT_NAV_LEARN":
            fresh_feedback=True
            reported[v["event"]]+=1
            if int(v["saved"]):reported["saved_updates"]+=1
        elif tag=="BOT_NAV_COST" and int(v["extra"])>0:
            reported["cost_uses"]+=1
            if loaded and loaded[-1]>0 and not fresh_feedback:
                recall_before_feedback+=1
                if first_restore is None: first_restore=[float(v["t"]),int(v["extra"])]
        elif tag=="BOT_NAV_FALLBACK":
            reported["fallback"]+=1
        elif tag=="BOT_NAV_COVERAGE" and "reachable_nodes" in v:
            coverage=[int(v["reachable_nodes"]),int(v["reachable_items"]),int(v["items_total"])]
        elif tag=="BOT_DUEL":
            decision=v; seen_reads=set();model_counts[v["model"]]+=1
        elif tag=="BOT_RED_READ":
            reads+=1
            if (decision and v["axis"] in ("forward","slide") and v["axis"] not in seen_reads and
                    v["life"]==decision["life"] and v["seq"]==decision["seq"] and
                    v["value"]==decision[v["axis"]]):
                good_reads+=1;seen_reads.add(v["axis"])
    result=dict(log_sha256=digest(path),scope_matched=bool(loaded),scopes=sorted({c[1] for c in contexts}),
                map_hashes=sorted({c[0] for c in contexts}),
                flags=sorted({c[2] for c in contexts}),cache_modes=sorted({c[4] for c in contexts}),
                loaded_edges=loaded,gear_models=dict(model_counts),gear_axis_reads=[good_reads,reads],
                samples=reported["samples"],teams=sorted(teams),target_teams=sorted(targets),sectors=len(sectors),
                graph=[nodes,edges],graph_ready=ready,coverage=coverage,moving_control_samples=motion,
                position_samples=positions,max_displacement_from_first_sample=round(max_displacement,3),
                nonzero_input_applications=applications,max_same_life_displacement=round(same_life_displacement,3),
                route=dict(arrivals=arrivals,stalls=stalls,saved_updates=reported["saved_updates"],
                           cost_uses=reported["cost_uses"],uses_before_any_local_feedback=recall_before_feedback,
                           first_prior_cost_game_time_and_cost=first_restore,local_steering_samples=reported["fallback"]))
    if scope.startswith("ctf/"):
        result["ctf"]=dict(bindings_seen=any(c[3] for c in contexts),flag_things=sorted(flags),
                           observed_carrier_things=sorted(carriers),home_states=sorted(homes),
                           valid_objective_samples=dict(objectives),team_score_sequence=scores,
                           local_pickup_hud=dict(local_hud),capture_hud=dict(capture_hud),
                           carrier_home_and_score_events=verified_capture)
    return result


def audit(root,schedule,overrides,partial):
    design=json.loads(schedule.read_text())
    rows=[]
    for spec in design["matrix"]+design["unseen"]:
        key=spec["name"]; dirname=overrides.get(key,key)
        if not re.fullmatch(r"[a-zA-Z0-9_.-]+",dirname) or dirname in (".",".."):
            raise ValueError("invalid attempt directory")
        path=root/dirname; receipt_path=path/"receipt.json"
        if not receipt_path.is_file():
            if partial:continue
            raise FileNotFoundError(receipt_path)
        receipt=json.loads(receipt_path.read_text()); scope="/".join((spec["mode"],
                "guns" if spec["weapons"]=="guns" else "sabers","force" if spec["force"]=="on" else "noforce"))
        run=dict(schedule_id=key,directory=dirname,map=spec["map"],map_sha256=spec["map_sha256"],scope=scope,
                 receipt_sha256=digest(receipt_path),match_status=receipt.get("status"),owners={})
        error=receipt.get("error","")
        if re.fullmatch(r"[a-zA-Z_]+",error or ""):run["launcher_error"]=error
        for side in ("dark","light"):
            log=path/(side+".log")
            if not log.exists():continue
            result=owner(log,scope,spec["map_sha256"])
            if receipt.get("log_sha256",{}).get(log.name)!=result["log_sha256"]:
                raise ValueError(f"{dirname}/{log.name}: logfile differs from receipt")
            run["owners"][side]=result
        if spec["mode"]=="ctf" and (path/"server.log").is_file():
            server=path/"server.log"; fingerprint=digest(server)
            if receipt.get("log_sha256",{}).get(server.name)!=fingerprint: raise ValueError("host log digest")
            counts=Counter(CAPTURE[line.strip()] for line in server.read_text(errors="replace").splitlines()
                           if line.strip() in CAPTURE)
            run["stock_host_capture_hud"]=dict(red=counts["red"],gold=counts["gold"],log_sha256=fingerprint)
        rows.append(run)
    return dict(schema=1,scope="Native owner observations from the frozen mode and unfamiliar-map runs.",
                schedule_sha256=digest(schedule),reader_sha256=digest(Path(__file__)),runs=rows)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs",type=Path,required=True)
    parser.add_argument("--schedule",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--attempt",action="append",default=[],metavar="SCHEDULE_ID=DIRECTORY")
    parser.add_argument("--partial",action="store_true")
    args=parser.parse_args()
    report=audit(args.runs,args.schedule,dict(x.split("=",1) for x in args.attempt),args.partial)
    args.output.write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
