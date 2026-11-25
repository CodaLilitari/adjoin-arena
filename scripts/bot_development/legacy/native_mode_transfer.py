"""Stage only digest-pinned multiplayer content and choose a map-scoped tactical policy."""
from pathlib import Path
import hashlib
import re
import shutil
from collections import Counter

HEX = re.compile(r"[a-f0-9]{64}")


def stage_episode(args, target, archive_index, catalog, digest):
    source = args.episode_file.resolve(strict=True)
    if (source.suffix.lower() != ".gob" or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}",source.stem)
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}\.jkl", args.map)
            or not HEX.fullmatch(args.episode_sha256) or not HEX.fullmatch(args.map_sha256)
            or digest(source) != args.episode_sha256):
        raise ValueError("native_transfer_invalid_episode_identity")
    dest = target / "episode" / (source.stem.lower()+".gob")
    with source.open("rb") as inp, dest.open("wb") as out:
        shutil.copyfileobj(inp,out,1024*1024)
    if digest(dest) != args.episode_sha256:
        raise ValueError("native_transfer_staged_episode_mismatch")
    entries = archive_index(dest)
    item = next((x for x in entries if x["name"].casefold()=="jkl/"+args.map.casefold()),None)
    if not item:
        raise ValueError("native_transfer_absent_map")
    sequence = next(x for x in entries if x["name"].casefold() == "episode.jk")
    with dest.open("rb") as inp:
        inp.seek(item["offset"]); actual=hashlib.sha256(inp.read(item["size"])).hexdigest()
        if sequence["size"]>1_048_576:raise ValueError("native_transfer_episode_manifest_too_large")
        inp.seek(sequence["offset"]); text=inp.read(sequence["size"])
    declared=re.findall(r"(?im)^\s*\d+:\s*\d+\s+\d+\s+LEVEL\s+([^\s#]+)",text.decode("latin1"))
    listing = catalog(target)
    selected = next((ep for ep in listing["episodes"] if ep["episode"].lower()==source.stem.lower()),None)
    if (actual!=args.map_sha256 or selected is None or args.map.lower() not in [m.lower() for m in selected["maps"]]
            or args.map.lower() not in [m.lower() for m in declared]):
        raise ValueError("native_transfer_map_or_episode_manifest_mismatch")
    is_ctf = bool(selected["type"] & 8)
    if is_ctf != (args.mode=="ctf"):
        raise ValueError("native_transfer_wrong_episode_for_rules")
    return dest, {"episode":source.stem.upper(),"episode_sha256":args.episode_sha256,"map":args.map,
                  "map_sha256":actual,"episode_type":selected["type"],"title":selected["title"],
                  "episode_manifest_sha256":hashlib.sha256(text).hexdigest()}


def selection(args, map_hash):
    if args.policy_weights:
        scope=f"{args.mode}/{args.weapons}/"+("force" if args.force=="on" else "noforce")
        weights=args.policy_weights.resolve(strict=True)
        if (args.trial_scope!=scope or args.trial_map_sha256!=map_hash or args.mode=="ctf" or args.weapons=="sabers"
                or hashlib.sha256(weights.read_bytes()).hexdigest()!=args.trial_weights_sha256):
            raise ValueError("native_transfer_trial_scope_or_weights_mismatch")
        return {"controller":"learned","reason":"explicit_experimental_candidate","path":str(weights),
                "sha256":args.trial_weights_sha256,"cell":{"mode":args.mode,"combat":args.weapons,
                "force":args.force=="on","map_sha256":map_hash}}
    if not args.policy_registry:
        return {"controller":"teacher","reason":"no_registry_requested","path":None,"sha256":None}
    from bots.tactical_registry import resolve
    return resolve(args.policy_registry,mode=args.mode,combat=args.weapons,force=args.force=="on",map_sha256=map_hash)


def cache_directory(root, profile, repo, data, output):
    root=root.resolve()
    if any(root==p or p in root.parents or root in p.parents for p in (repo,data,output)):
        raise ValueError("native_transfer_cache_overlaps_inputs_or_output")
    if not root.is_dir() or not re.fullmatch(r"[a-z0-9_]+",profile):
        raise ValueError("native_transfer_invalid_cache_directory")
    cache=(root/profile).resolve()
    if cache.parent!=root:
        raise ValueError("native_transfer_invalid_profile_cache")
    cache.mkdir(exist_ok=True)
    return cache


def read_native(directory, receipt):
    config = receipt["mode_transfer"]
    mode, weapon, force = config["mode"], config["weapons"], config["force"]
    scope = f"{mode}/{weapon}/" + ("force" if force=="on" else "noforce")
    checks = []
    owners = {}
    for side, team in (("dark",1), ("light",2)):
        contexts, sectors, teams, objectives = [],set(),set(),Counter()
        valid_objectives = Counter()
        nav = Counter()
        flags, carriers, home, scores, nav_teams = set(), set(), set(), [], Counter()
        graph, moved = False,False
        model_counts = Counter()
        for line in (directory/(side+".log")).read_text(errors="replace").splitlines():
            tag=line.partition(" ")[0]
            if tag not in ("BOT_RED_CONTEXT","BOT_RED_NAV","BOT_DUEL","BOT_NAV_LEARN","BOT_NAV_COST","BOT_NAV_FALLBACK"):
                continue
            d=dict(word.split("=",1) for word in line.split()[1:] if "=" in word)
            if tag=="BOT_RED_CONTEXT":
                contexts.append(d)
            elif tag=="BOT_DUEL":
                model_counts[d["model"]]+=1
            elif tag=="BOT_RED_NAV":
                if d["scope"]!=scope:
                    continue
                teams.add(int(d["team"])); sectors.add(int(d["sector"]));nav_teams[(d["team"],d["target_team"])]+=1
                graph |= bool(int(d["ready"]) and int(d["nodes"])>0 and int(d["edges"])>0)
                moved |= abs(float(d["fwd"]))+abs(float(d["slide"]))>0
                objectives[d["objective"]]+=1
                if int(d["objective_valid"]):valid_objectives[d["objective"]]+=1
                pair=lambda key:tuple(map(int,d[key].split(",")))
                flags.add(pair("flags"));carriers.add(pair("carriers"));home.add(pair("home"))
                score=(int(d["red_score"]),int(d["gold_score"]))
                if not scores or score!=scores[-1]:scores.append(score)
            else:
                nav[tag+("/"+d["event"] if "event" in d else "")]+=1
        settled=[c for c in contexts if c["scope"]==scope and c["map_sha"]==config["content"]["map_sha256"]]
        if not settled:
            checks.append(side+"_rules_or_map_unverified")
        else:
            c=settled[-1];bits=int(c["flags"],16)
            if (int(c["rank"])!=(8 if force=="on" else 0) or int(c["sabers"])!=int(weapon=="sabers")
                    or int(c["force"])!=int(force=="on") or int(c["bindings"])!=int(mode=="ctf")
                    or bool(bits&1)!=(mode!="ffa") or (mode=="tdm" and not bits&0x100)
                    or int(c["scope_match"])!=int(side==receipt["red_policy"]["model_side"])):
                checks.append(side+"_native_context_mismatch")
        if (team if mode!="ffa" else 0) not in teams:
            checks.append(side+"_requested_team_unobserved")
        if not moved or not sectors:checks.append(side+"_navigation_unobserved")
        if mode=="ctf" and not any(a>=0 and b>=0 and a!=b for a,b in flags):
            checks.append(side+"_two_flags_unobserved")
        owners[side]=dict(contexts=contexts,teams=sorted(teams),sectors=sorted(sectors),graph_ready=graph,
                          movement_seen=moved,objectives=dict(objectives),valid_objectives=dict(valid_objectives),
                          flags=sorted(flags),carriers=sorted(carriers),flag_home_states=sorted(home),
                          team_score_changes=scores,cache_and_navigation_events=dict(nav),
                          effective_duel_models=dict(model_counts),
                          observed_team_and_target_team={a+","+b:n for (a,b),n in nav_teams.items()})
    return {"owners":owners,"qualification_errors":checks}
