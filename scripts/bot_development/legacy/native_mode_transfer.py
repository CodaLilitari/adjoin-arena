"""Stage only digest-pinned multiplayer content and choose a map-scoped tactical policy."""
from pathlib import Path
import hashlib
import math
import re
import shutil
from collections import Counter

HEX = re.compile(r"[a-f0-9]{64}")


def custom_environment(content, mode, *, endpoint=None):
    """Forward pins obtained from the staged GOB and its declared JKL to the native join check."""
    environment = {"ADJOIN_CUSTOM_EPISODE": content["episode"], "ADJOIN_CUSTOM_MAP": content["map"],
            "ADJOIN_CUSTOM_GOB_SHA256": content["episode_sha256"],
            "ADJOIN_CUSTOM_MAP_SHA256": content["map_sha256"], "ADJOIN_CUSTOM_MODE": mode}
    if endpoint is not None:
        environment["ADJOIN_CUSTOM_ENDPOINT"] = endpoint
    return environment


def stage_route_hint(args, content, target):
    scope = f"{args.mode}/{args.weapons}/" + ("force" if args.force == "on" else "noforce")
    raw = args.route_hint.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if not HEX.fullmatch(args.route_hint_sha256) or digest != args.route_hint_sha256 or args.route_hint_scope != scope:
        raise ValueError("native route file or ruleset differs from requested pins")
    words = raw.decode("ascii").split()
    if (len(words) < 3 or words[0] != "RED_ROUTE_HINT_V1" or words[1] != content["map_sha256"]
            or not words[2].isdigit() or not 2 <= int(words[2]) <= 32 or len(words[3:]) != 5 * int(words[2])):
        raise ValueError("native route format, waypoint count or JKL digest mismatch")
    points = [list(map(int, words[i:i+5])) for i in range(3, len(words), 5)]
    with target.open("xb") as stream:
        stream.write(raw)
    return {"format": words[0], "map_sha256": words[1], "waypoints": len(points), "sha256": digest,
            "scope": scope, "waypoint_sectors": [p[0] for p in points], "waypoint_fixtures": [p[1] for p in points]}


def route_observations(path, expected, pid):
    ready = False
    lives = {}
    with path.open(errors="replace") as stream:
        for number, line in enumerate(stream, 1):
            if not line.startswith("BOT_ROUTE_HINT "):
                continue
            d = dict(token.split("=", 1) for token in line.split()[1:] if "=" in token)
            if (d.get("pid") != str(pid) or d.get("hint_sha") != expected["sha256"]
                    or d.get("map_sha") != expected["map_sha256"]):
                raise ValueError("native route hint process or content mismatch")
            phase, status = d["phase"], d["status"]
            if phase == "load":
                if status != "ready":
                    raise ValueError("native route file was rejected")
                ready = True
                continue
            if not ready:
                raise ValueError("native route used before the file was accepted")
            life = lives.setdefault(d["life"], {"started": False, "steering_samples": 0, "arrivals": [],
                                                "blocked": {}, "exits": []})
            seq, fixture, sector = int(d["seq"]), int(d["fixture"]), int(d["sector"])
            if phase == "start" and status == "ready":
                life["started"] = True
                life["start"] = {"line": number, "sector": sector, "fixture": fixture, "pos": d["pos"]}
            elif phase == "step" and status == "applied":
                life["steering_samples"] += int(bool(float(d["fwd"]) or float(d["slide"])))
            elif phase == "arrive" and status == "reached":
                if (not 0 <= seq < expected["waypoints"] - 1 or expected["waypoint_sectors"][seq] != sector
                        or expected["waypoint_fixtures"][seq] != fixture):
                    raise ValueError("native waypoint arrival on the wrong fixture or sector")
                life["arrivals"].append(seq)
            elif phase == "blocked":
                life["blocked"][status] = life["blocked"].get(status, 0) + 1
            elif phase == "exit" and status == "reached":
                if (not life["started"] or seq != expected["waypoints"] - 1 or not life["steering_samples"]
                        or life["arrivals"] != list(range(seq)) or sector != expected["waypoint_sectors"][-1]):
                    raise ValueError("native terminal crossing lacks same-life ordered waypoint evidence")
                life["exits"].append({"line": number, "sector": sector, "fixture": fixture, "pos": d["pos"]})
    if not ready:
        raise ValueError("native route file was never accepted")
    return {"load_verified": True, "lives": lives}


def verify_custom_admission(path, content, mode, pid):
    expected = {"status": "accepted", "episode": content["episode"], "map": content["map"],
                "gob_sha": content["episode_sha256"], "map_sha": content["map_sha256"],
                "mode": mode, "pid": str(pid)}
    accepted = {}
    first_control = None
    with path.open(errors="replace") as stream:
        for number, line in enumerate(stream, 1):
            tag = line.partition(" ")[0]
            if tag == "BOT_RED_CUSTOM":
                details = dict(token.split("=", 1) for token in line.split()[1:] if "=" in token)
                if any(details.get(key) != value for key, value in expected.items()):
                    raise ValueError("native custom episode, process, map or rules mismatch")
                phase = details.get("phase")
                if phase not in ("admission", "world"):
                    raise ValueError("unknown native custom admission phase")
                accepted.setdefault(phase, number)
            elif tag in ("BOT_RED_FIRST", "BOT_RED_APPLY") and first_control is None:
                first_control = number
    if (first_control is None or set(accepted) != {"admission", "world"}
            or not accepted["admission"] < accepted["world"] < first_control):
        raise ValueError("native custom content must be admitted and loaded before first control")
    return {"admission_line": accepted["admission"], "world_line": accepted["world"],
            "first_control_line": first_control, **expected}


def platform_observations(path):
    """Bind a sampled support decision to later living native positions in the same life."""
    samples = []
    seen = set()
    life = None
    event_count = 0
    with path.open(errors="replace") as stream:
        for number, line in enumerate(stream, 1):
            tag, _, rest = line.partition(" ")
            if tag not in ("BOT_RED_FIRST", "BOT_RED_STATE", "BOT_PLATFORM_SUPPORT", "BOT_STATUS"):
                continue
            data = dict(token.split("=", 1) for token in rest.split() if "=" in token)
            if tag in ("BOT_RED_FIRST", "BOT_RED_STATE"):
                life = int(data["life"])
            elif tag == "BOT_PLATFORM_SUPPORT":
                event_count += 1
                key = (life, data["sector"], data["fixture"])
                if key in seen or len(samples) >= 24:
                    continue
                seen.add(key)
                samples.append({"line": number, "life": life, "event": data, "post_marker_positions": 0,
                                "max_xy_displacement": 0.0, "reached_another_sector": False})
            elif float(data["health"]) > 0:
                xy = tuple(map(float, data["pos"].split(",")[:2]))
                for sample in samples:
                    if life is None or life != sample["life"]:
                        continue
                    start = tuple(map(float, sample["event"]["pos"].split(",")[:2]))
                    distance = math.dist(start, xy)
                    sample["post_marker_positions"] += 1
                    if distance > sample["max_xy_displacement"]:
                        sample.update(max_xy_displacement=distance, farthest_position_line=number,
                                      farthest_position=data["pos"], farthest_sector=data["sector"])
                    sample["reached_another_sector"] |= data["sector"] != sample["event"]["sector"]
    return {"native_support_events": event_count, "sampled_per_life_and_fixture": samples}


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
        if "custom_admission" in config:
            try:
                pid = receipt["pace_experiment"]["loaded_images"][side]["pid"]
                owners[side]["custom_admission"] = verify_custom_admission(
                    directory / (side + ".log"), config["content"], mode, pid)
            except ValueError as error:
                checks.append(side + ": " + str(error))
        if config.get("mesh_support"):
            owners[side]["mesh_support"] = platform_observations(directory / (side + ".log"))
        if "route_hint" in config:
            try:
                owners[side]["route_hint"] = route_observations(directory / (side + ".log"),
                    config["route_hint"], receipt["pace_experiment"]["loaded_images"][side]["pid"])
            except ValueError as error:
                checks.append(side + ": " + str(error))
    return {"owners":owners,"qualification_errors":checks}
