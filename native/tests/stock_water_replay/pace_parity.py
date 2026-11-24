"""Compare one committed native swimmer case at 1x and without wall pacing."""
import argparse
import csv
import hashlib
import itertools
import json
import math
import statistics
import subprocess
import sys
import time
from pathlib import Path

from collect_motor import case_environment
from evaluate_motor import assess
from geometry import write_geometry
from run import HERE, build_replay

CASES = HERE / "bank_cases.tsv"
REFERENCE = HERE.parents[2] / "qa/bots-bank-landing.json"
HZ = 150
LOGS = ("start.json", "motor.jsonl", "native.jsonl", "pace.jsonl")


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def differing_field(a, b, prefix=""):
    if type(a) is type(b) is dict:
        for key in sorted(a.keys() | b.keys()):
            path = f"{prefix}.{key}" if prefix else key
            if key not in a or key not in b:
                return path
            if canonical(a[key]) != canonical(b[key]):
                return differing_field(a[key], b[key], path)
    if type(a) is type(b) is list:
        for i in range(max(len(a), len(b))):
            path = f"{prefix}[{i}]"
            if i >= min(len(a), len(b)):
                return path
            if canonical(a[i]) != canonical(b[i]):
                return differing_field(a[i], b[i], path)
    return prefix or "(record)"


def read_rows(path):
    with path.open(encoding="utf-8") as stream:
        for n, line in enumerate(stream, 1):
            if not line.endswith("\n"):
                raise ValueError(f"{path.name} row {n} is truncated")
            record = json.loads(line)
            require(isinstance(record, dict), f"{path.name} row {n} is not an object")
            yield record


def known_case(name, yaw):
    with CASES.open(encoding="utf-8", newline="") as stream:
        matches = [r for r in csv.DictReader(stream, delimiter="\t") if r["case"] == name]
    require(len(matches) == 1 and yaw in map(int, matches[0]["yaw_offsets"].split(",")),
            f"No unique committed start for {name} at yaw {yaw}")
    ref = json.loads(REFERENCE.read_bytes())
    rows = (dict(zip(ref["matrix_columns"], r)) for r in ref["matrix_rows"])
    expected = [r for r in rows if r["case"] == name and r["yaw_deg"] == yaw]
    require(len(expected) == 1 and type(expected[0]["corrected_dry_s"]) in (int, float),
            "No committed supported landing for requested start")
    return matches[0], expected[0]


def first_difference(reference, candidate, *, partial=False):
    """Find the earliest diverging simulation coordinate across all trace files."""
    differences = []
    for name in LOGS:
        left, right = reference / name, candidate / name
        if partial and not (left.is_file() and right.is_file()):
            continue
        if sha(left) == sha(right):
            continue
        # An unchanged parsed object is identical even if JSON formatting differs.
        try:
            for n, (a, b) in enumerate(itertools.zip_longest(read_rows(left), read_rows(right)), 1):
                if canonical(a) == canonical(b):
                    continue
                row = a if a is not None else b
                differences.append(dict(file=name, field=differing_field(a, b), line=n,
                                        tick=row.get("tick", row.get("ticks")), step=row.get("step"),
                                        reference=a, candidate=b))
                break
        except (ValueError, OSError):
            if not partial:
                raise
    def coordinate(d):
        return (d["step"] if type(d["step"]) is int else -1,
                d["tick"] if type(d["tick"]) is int else -1, LOGS.index(d["file"]))
    return min(differences, key=coordinate, default=None)


def hex_number(value):
    if not isinstance(value, str) or not value.lower().lstrip("-").startswith("0x"):
        return False
    try:
        return math.isfinite(float.fromhex(value))
    except (ValueError, OverflowError):
        return False


def validate_pace(path, native, dt):
    """Validate order, tick/substep work coverage, control cadence, and landing."""
    ticks = steps = 0
    streak = 0
    digest = hashlib.sha256()
    terminal = None
    last_step = None
    current_tick = -1
    for n, row in enumerate(read_rows(path), 1):
        where = f"{path.name} row {n} tick={row.get('tick')} step={row.get('step')}"
        for key in ("tick", "step", "streak", "sector", "attached_sector", "attached_surface",
                    "attach_flags", "physics_flags", "actor_flags", "thing_flags", "endurance"):
            require(type(row.get(key)) is int, f"{where}: invalid {key}")
        require(row.get("owner") == "baseline" and type(row.get("stage")) is str,
                f"{where}: invalid owner or stage")
        for key in ("wet", "water_surface"):
            require(type(row.get(key)) is bool, f"{where}: invalid {key}")
        for key in ("position", "velocity", "facing", "up"):
            vector = row.get(key)
            require(isinstance(vector, list) and len(vector) == 3 and all(map(hex_number, vector)),
                    f"{where}: invalid {key}")
        for key in ("health", "head_pitch"):
            require(hex_number(row.get(key)), f"{where}: invalid {key}")
        require(terminal is None, f"{where}: row after terminal")
        kind = row.get("kind")
        if kind == "control":
            require(row["tick"] == ticks and row["step"] == steps, f"{where}: incomplete control")
            require(row["stage"] == "inputs" and row["streak"] == streak, f"{where}: invalid control state")
            # The engine rounds total elapsed control time to the nearest substep.
            require(abs(steps - ticks * dt * HZ) <= 0.501, f"{where}: incorrect control cadence")
            current_tick = ticks
            ticks += 1
        elif kind == "step":
            require(current_tick >= 0 and row["tick"] == current_tick and row["step"] == steps + 1,
                    f"{where}: incomplete physics substep")
            steps += 1
            require(row["stage"] == "integrated", f"{where}: expected a live integrated step")
            supported = (not row["wet"] and row["sector"] == row["attached_sector"] == native["sector"]
                         and row["attached_surface"] >= 0)
            streak = streak + 1 if supported else 0
            require(row["streak"] == streak <= 38, f"{where}: incorrect dry-support streak")
            last_step = row
        elif kind == "terminal":
            require(current_tick >= 0 and row["step"] == steps and row["tick"] == current_tick,
                    f"{where}: invalid terminal coordinates")
            terminal = row
        else:
            raise ValueError(f"{where}: unknown event kind {kind}")
        digest.update((canonical(row) + "\n").encode("utf-8"))
    require(ticks > 0 and steps > 0 and last_step is not None and terminal is not None,
            "Missing work or physical terminal")
    require(steps == native["physics_steps"] and ticks == native["control_ticks"]
            and terminal["result"] == native["terminal"] == "supported_dry", "Terminal/work mismatch")
    require(terminal["streak"] == 38 and last_step["streak"] == 38
            and terminal["sector"] == terminal["attached_sector"] == native["sector"]
            and not terminal["wet"] and terminal["attached_surface"] >= 0
            and float.fromhex(terminal["health"]) == native["health"], "Unsupported final landing")
    final_state = {**last_step, "kind": "terminal", "result": "supported_dry"}
    require(canonical(terminal) == canonical(final_state), "Terminal differs from final physics step")
    return digest.hexdigest()


def check_pacing(elapsed, ticks, dt, paced):
    require(math.isfinite(elapsed) and elapsed > 0, "Invalid elapsed wall time")
    if paced:
        # Last control deadline is (ticks-1)*dt. Startup and scheduling only add time.
        require(elapsed + .025 >= (ticks-1) * dt, "1x run finished before its last control deadline")


def summarize_times(samples):
    timings = {}
    for mode in ("1x", "uncapped"):
        times = [s["wall_seconds"] for s in samples if s["mode"] == mode]
        timings[mode] = dict(median=statistics.median(times), minimum=min(times),
                             maximum=max(times), samples=len(times))
    lower = timings["1x"]["minimum"] / timings["uncapped"]["maximum"]
    return dict(timings=timings, median_speedup=timings["1x"]["median"]/timings["uncapped"]["median"],
                minimum_observed_ratio=lower,
                acceleration="observed" if lower > 1 else "inconclusive")


def run_sample(folder, executable, geometry, row, yaw, expected, paced, summary):
    folder.mkdir()
    env = case_environment(row, yaw)
    env.update(LILY_BANK_TRACE=str(folder / "native.jsonl"),
               LILY_INDEPENDENT_TRACE=str(folder / "motor.jsonl"),
               LILY_INDEPENDENT_ORIGIN=str(folder / "start.json"), LILY_HOLD_TICKS="1",
               LILY_PACE_TRACE=str(folder / "pace.jsonl"))
    if paced:
        env["LILY_REPLAY_REALTIME"] = "1"
    command = [executable, geometry, *[row[k] for k in ("origin", "wet", "dry", "start_sector", "control_dt")]]
    with (folder / "engine.log").open("wb") as log:
        start = time.perf_counter()
        try:
            proc = subprocess.run(command, env=env, stdout=log, stderr=log, timeout=90, check=False)
        finally:
            summary["wall_seconds"] = time.perf_counter() - start
    summary["return_code"] = proc.returncode
    require(proc.returncode == 0, f"Expected a supported landing (engine exit {proc.returncode})")
    dt = float(row["control_dt"])
    job = dict(controller="baseline", target_sector=int(row["dry"]), hold_ticks=1, control_dt=dt, yaw_deg=yaw)
    native = assess(job, folder, proc.returncode, row)
    require(native["physical_success"] is True and native["ownership_complete"] is True,
            "Incomplete native baseline landing")
    summary["canonical_pace_sha256"] = validate_pace(folder / "pace.jsonl", native, dt)
    # Committed reference times are rounded to milliseconds; recover the discrete step.
    require(native["physics_steps"] == round(expected["corrected_dry_s"] * HZ)
            and native["sector"] == expected["dry_sector"] and native["health"] == expected["hp_at_dry"],
            "Landing differs from the committed physical baseline")
    check_pacing(summary["wall_seconds"], native["control_ticks"], dt, paced)
    summary.update(control_ticks=native["control_ticks"], physics_steps=native["physics_steps"],
                   sim_seconds=native["elapsed_sim_seconds"], terminal=native["terminal"], seed=native["seed"])
    summary["trace_sha256"] = {name: sha(folder / name) for name in LOGS}


def prepare_build(args, output):
    work = output / "build"
    work.mkdir()
    if args.executable:
        require(args.geometry and not args.source and not args.build,
                "Prebuilt mode needs --executable and --geometry")
        exe, geom = args.executable.resolve(), args.geometry.resolve()
        converted = work / "map.numeric"
        write_geometry(args.map, converted)
        require(sha(converted) == sha(geom), "Prebuilt geometry disagrees with supplied map")
        return exe, geom, dict(mode="prebuilt", executable_sha256=sha(exe),
                               geometry_sha256=sha(geom), map_sha256=sha(args.map))
    require(args.source and args.build and not args.geometry,
            "Build mode needs --source and --build")
    exe, geom, provenance = build_replay(args.source, args.build, args.map, work, independent_motor=True)
    return exe, geom, dict(mode="compiled", geometry_sha256=sha(geom), **provenance)


def run(args):
    output = args.output.resolve()
    require(not any((p / ".git").exists() for p in (output, *output.parents)),
            "Choose an external output directory outside a Git checkout")
    require(args.samples >= 2, "Provide at least two samples per mode")
    row, expected = known_case(args.case, args.yaw)
    output.mkdir(parents=True, exist_ok=False)
    receipt = dict(schema=1, scope="single native stock-water actor", status="incomplete",
                   case=row, yaw=args.yaw, samples_per_mode=args.samples,
                   timing="fresh process start to exit, excluding build, comparison and hashing",
                   cases_sha256=sha(CASES), expected_landing=expected, reference_sha256=sha(REFERENCE),
                   samples=[])
    try:
        exe, geom, receipt["build"] = prepare_build(args, output)
        fixture = [*sorted(HERE.glob("*.inc")), *sorted(HERE.glob("*.h")), HERE / "replay.c",
                   HERE / "run.py", HERE / "collect_motor.py", HERE / "evaluate_motor.py",
                   HERE / "evaluate_bank.py", HERE / "geometry.py", HERE / "pace_parity.py",
                   HERE.parent / "test_bot_portal_collision.c"]
        receipt["fixture_sha256"] = {p.relative_to(HERE.parent).as_posix(): sha(p) for p in fixture}
        baseline = None
        for mode in ("1x", "uncapped"):
            for n in range(args.samples):
                folder = output / f"{mode}-{n+1}"
                sample = dict(mode=mode, sample=n+1, directory=folder.name)
                receipt["samples"].append(sample)
                try:
                    run_sample(folder, exe, geom, row, args.yaw, expected, mode == "1x", sample)
                except (ValueError, TypeError, KeyError, IndexError, OSError, subprocess.SubprocessError):
                    if baseline is not None:
                        try:
                            mismatch = first_difference(baseline, folder, partial=True)
                            if mismatch:
                                receipt["first_difference"] = mismatch
                        except (ValueError, TypeError, OSError) as error:
                            receipt["comparison_error"] = str(error)
                    raise
                if baseline is None:
                    baseline = folder
                else:
                    difference = first_difference(baseline, folder)
                    if difference:
                        receipt["first_difference"] = difference
                        raise ValueError(f"Trace mismatch in {difference['file']} at "
                                         f"tick {difference['tick']}, step {difference['step']}")
        receipt.update(summarize_times(receipt["samples"]), trajectory_parity="passed")
        receipt["status"] = "passed"
    except (ValueError, TypeError, KeyError, IndexError, OSError, subprocess.SubprocessError) as error:
        receipt.update(status="failed", error=f"{type(error).__name__}: {error}")
        return False
    finally:
        (output / "receipt.json").write_text(json.dumps(receipt, indent=2, allow_nan=False) + "\n")
        print(f"{receipt['status']}: {output / 'receipt.json'}")
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, help="Patched PR #2 engine source")
    parser.add_argument("--build", type=Path, help="Native CMake build directory")
    parser.add_argument("--executable", type=Path, help="Already-built instrumented fixture")
    parser.add_argument("--geometry", type=Path, help="Geometry given to prebuilt fixture")
    parser.add_argument("--map", type=Path, required=True, help="Owned stock Canyon Oasis JKL")
    parser.add_argument("--output", type=Path, required=True, help="New external directory")
    parser.add_argument("--case", default="pool-90")
    parser.add_argument("--yaw", type=int, default=0)
    parser.add_argument("--samples", type=int, default=3, help="Runs per mode")
    args = parser.parse_args()
    try:
        return 0 if run(args) else 1
    except (OSError, ValueError) as error:
        parser.exit(2, f"{error}\n")


if __name__ == "__main__":
    sys.exit(main())
