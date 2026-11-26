"""Score original and controlled JHS openings from private headless JKWeb owner logs."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import time

from .jhs_route_geometry import resource
from ..map_coverage import JHS_GOB, JHS_MAP, ROOT
from ..score_map_coverage import JHS_REGIONS


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def score_room(label, directory, archive, trace_name):
    room = next((directory / "room").glob("headless-*/headless.json")).parent
    roster = json.loads((room / "headless.json").read_bytes())["seats"]
    owner = json.loads((room / "lily" / "run.json").read_bytes())
    joined_room = owner.get("hosted") or owner.get("external") or {}
    if joined_room.get("map", "").lower() != "jhs.jkl" or not all(s["joined"] for s in roster.values()):
        raise ValueError(f"{label}: expected a joined JHS room")
    sample_file = directory / "samples.json"
    observer = json.loads(sample_file.read_bytes())
    players = {}
    for name in roster:
        console = room / (name + ".console.log")
        status = [dict(re.findall(r"(\w+)=([^\s]+)", row.partition("BOT_STATUS ")[2]))
                  for row in console.read_text(errors="replace").splitlines() if "BOT_STATUS " in row]
        alive = [row for row in status if float(row["health"]) > 0]
        positions = [row[name]["observed"]["position"] for row in observer if name in row
                     and row[name].get("observed", {}).get("health", 0) > 0]
        players[name] = dict(native_status_samples=len(alive), sectors=sorted({int(row["sector"]) for row in alive}),
                             position_samples=len(positions), max_live_z=round(max(p[2] for p in positions), 5)
                             if positions else None, console_sha256=digest(console))
    archive_hash = digest(archive)
    map_hash = hashlib.sha256(resource(archive, "jkl/jhs.jkl")).hexdigest()
    original = archive_hash == JHS_GOB and map_hash == JHS_MAP
    report = dict(opening=label, original_starts=original, episode_sha256=archive_hash, map_sha256=map_hash,
                  wasm_sha256=digest(directory / "binary/openjkdf2.wasm"),
                  js_sha256=digest(directory / "binary/openjkdf2.js"), mode=owner["mode"], owners=players,
                  paired_poll_sha256=digest(sample_file))
    coach_log = directory / "coach/log.jsonl"
    if coach_log.is_file():
        events = []
        for line in coach_log.read_bytes().splitlines():
            row = json.loads(line)
            if row.get("kind") in ("jhs_roof_start", "jhs_roof_end"):
                events.append({k: row[k] for k in ("kind", "route", "content", "attempt", "sector",
                                                    "game_time", "reason") if k in row})
        report["coach"] = {"events": events, "log_sha256": digest(coach_log)}
        receipt = directory / "coach-source-sha256.json"
        if receipt.is_file():
            report["coach"]["source_sha256"] = json.loads(receipt.read_text(encoding="utf-8-sig"))
    if trace_name == "-":
        return report
    return report | score_trace(directory / trace_name, label)


def score_trace(path, label=""):
    report = {}
    sectors, outcomes, shield_samples = Counter(), Counter(), Counter()
    milestones = []
    previous, roof_samples, established = None, 0, set()
    reached, last_observed, roof_witness = False, None, []
    low, shaft = set(), set()
    ground, high_car, on_car, approached, hall = set(), {}, set(), set(), set()
    first_living = None
    hall_roof = shuttle_roof = False
    max_z = first_clock = first_game_clock = None
    policies = set()
    for line in path.read_bytes().splitlines():
        row = json.loads(line)
        if row.get("policy_hash"):
            policies.add(row["policy_hash"])
        if row["event"] == "outcome":
            outcomes[row["status"]] += 1
        if row["event"] != "observation" or not row.get("sense"):
            continue
        sense, clock = row["sense"], row["monotonic_seconds"]
        game_clock = row.get("state", {}).get("game_time")
        first_clock = clock if first_clock is None else first_clock
        if first_game_clock is None:
            first_game_clock = game_clock
        life = (row["run_id"], row["world_epoch"], row["life_epoch"])
        if not sense.get("self") or sense["self"]["health"] <= 0:
            previous, last_observed, roof_samples = None, None, 0
            continue
        sector = sense["self"]["sector"]
        shield_samples[str(round(sense["self"]["shields"], 2))] += 1
        x, y, z = sense["position"]
        if first_living is None:
            first_living = dict(sector=sector, position=[round(v, 5) for v in (x, y, z)], life=life[-1])
        if z <= .5:
            ground.add(life)
        if sector == 79 and z < 3.05:
            hall.add(life)
        if sector not in (30, 31, 0):
            low.discard(life)
            shaft.discard(life)
        if sector not in (0, 16, 19) or z < 4.15:
            on_car.discard(life)
            approached.discard(life)
        if life in ground and sector == 16 and z >= 4.46 and sense["supported"]:
            on_car.add(life)
            high_car.setdefault(life, dict(life=life[-1], sector=16, sample_id=sense["sample_id"],
                                           elapsed_game_s=round(game_clock-first_game_clock, 3),
                                           position=[round(v, 5) for v in (x, y, z)]))
        if life in on_car and sector == 19 and z >= 4.4:
            approached.add(life)
        sectors[sector] += 1
        max_z = z if max_z is None else max(z, max_z)
        if sector == 30 and z < 3.005:
            low.add(life)
        if life in low and sector == 31 and z >= 3.005:
            shaft.add(life)
        on_roof = sector in JHS_REGIONS["roof"] and z >= 4.545 and sense["supported"]
        roof_samples = roof_samples + 1 if on_roof and previous == life else int(on_roof)
        previous = life
        observed = dict(life=life[-1], sample_id=sense["sample_id"], sector=sector, z=round(z, 5),
                        elapsed_game_s=round(game_clock-first_game_clock, 3) if game_clock is not None else None,
                        health=round(sense["self"]["health"], 1), supported=sense["supported"])
        if life in shaft and roof_samples >= 2 and last_observed["sample_id"] != sense["sample_id"]:
            reached = True
            hall_roof |= life in hall
            if not roof_witness:
                roof_witness = [last_observed, observed]
        if life in approached and roof_samples >= 2 and last_observed["sample_id"] != sense["sample_id"]:
            shuttle_roof = True
            if not roof_witness:
                roof_witness = [last_observed, observed]
        last_observed = observed
        if sector in (30, 31, 0) and (life, sector) not in established:
            established.add((life, sector))
            milestones.append(dict(life=life[-1], sector=sector, elapsed_wall_s=round(clock-first_clock, 3),
                                   elapsed_game_s=round(game_clock-first_game_clock, 3) if game_clock is not None else None,
                                   position=[round(v, 5) for v in (x, y, z)], supported=sense["supported"]))
    report["lily_trace"] = dict(trace_sha256=digest(path), policy_hashes=sorted(policies),
                                live_sense_counts=dict(sorted(sectors.items())), motor_outcomes=dict(outcomes),
                                max_live_z=round(max_z, 5) if max_z is not None else None,
                                first_observed_per_life=milestones, supported_roof_witness=roof_witness,
                                first_living_sample=first_living, same_life_deck_to_supported_roof=reached,
                                same_life_hall_deck_roof=hall_roof, ground_to_upper_shuttle=list(high_car.values()),
                                same_life_ground_shuttle_roof=shuttle_roof)
    if label.startswith("grate-sensor-"):
        report["grate_diagnostic"] = dict(
            intact_samples=shield_samples["91.0"], damage_message_samples=shield_samples["77.0"],
            accepted_damage_samples=shield_samples["43.0"],
            method="Private diagnostic copy of stock grate COG periodically reports its state in the solo player's shields. Only surface 868 reports. The position and movement tests use owner sense samples.")
    return report


def record(manifest, output, seconds):
    from bots.companion_cli import call, load_private
    if output.resolve().is_relative_to(ROOT):
        raise ValueError("Record outside the repository")
    seats = json.loads(manifest.read_bytes())["seats"]
    cred = load_private(Path(seats["lily"]["companion_credential"]))
    previous, count = None, 0
    end = time.monotonic() + seconds
    with output.open("x", encoding="utf-8", buffering=1) as trace:
        while time.monotonic() < end:
            try:
                obs = call(cred, "observation")
                sense = (obs.get("lily") or {}).get("sense")
                if sense and sense.get("self"):
                    fence = {k: obs[k] for k in ("run_id", "world_epoch", "life_epoch")}
                    marker = (*fence.values(), sense["sample_id"])
                    if marker != previous:
                        previous = marker
                        row = dict(fence, event="observation", monotonic_seconds=time.monotonic(),
                                   state={"game_time": obs["state"].get("game_time")},
                                   sense={k: sense[k] for k in ("sample_id", "position", "supported", "self")})
                        trace.write(json.dumps(row, separators=(",", ":")) + "\n")
                        count += 1
            except (OSError, ValueError):
                if count:
                    break
            time.sleep(.035)
    if not count:
        raise ValueError("No owner sense samples recorded")
    return count


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--run", action="append", nargs=4, metavar=("OPENING", "ROOM_DIR", "GOB", "TRACE_OR_DASH"))
    mode.add_argument("--record", type=Path, metavar="HEADLESS_JSON", help="Observe adaptive Lily without acquiring a lease.")
    mode.add_argument("--score-trace", type=Path, help="Score a saved high-rate owner trace.")
    p.add_argument("--output", type=Path)
    p.add_argument("--seconds", type=int, default=60)
    args = p.parse_args()
    if args.record:
        if not args.output or not 1 <= args.seconds <= 3600:
            p.error("--record requires a new external --output and --seconds 1..3600")
        print(f"Recorded {record(args.record, args.output, args.seconds)} owner samples.")
        raise SystemExit
    if args.score_trace:
        result = score_trace(args.score_trace)
    else:
        rows = [score_room(name, Path(room), Path(gob), trace) for name, room, gob, trace in args.run]
        result = {"schema": 1, "score": "Same-life lift or shuttle approach followed by two living supported roof samples at or above 4.545.", "runs": rows}
    encoded = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")
