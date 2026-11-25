"""Update Red's neural policy after each completed training match, retaining every revision."""
import argparse
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import time

from . import red_tactical_policy as policy


def sha(data):
    return hashlib.sha256(data).hexdigest()


def atomic_write(path, data):
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as tmp:
        try:
            tmp.write(data)
            tmp.flush()
            os.fsync(tmp.fileno())
        except BaseException:
            tmp.close()
            Path(tmp.name).unlink(missing_ok=True)
            raise
    try:
        os.replace(tmp.name, path)
    finally:
        Path(tmp.name).unlink(missing_ok=True)


@contextmanager
def writer(folder):
    """Release the OS lock even when a watcher exits mid-update."""
    with (folder / ".update.lock").open("a+b") as handle:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def load_weights(folder, key):
    path = folder / "weights" / (key + ".weights")
    data = path.read_bytes()
    policy.require(sha(data) == key, "Retained weights failed their hash check")
    return policy.Model.decode(data)


def check_challenger(folder, history, rows):
    """Score the old candidate on new teacher decisions *before* learning from them."""
    previous = history["matches"][-1] if history["matches"] else {}
    candidate = previous.get("candidate")
    incumbent = previous.get("practice")
    record = {"challenger": candidate, "incumbent": incumbent, "practice": incumbent}
    if not candidate or candidate == incumbent:
        return dict(record, decision="no_new_challenger")
    groups = policy.encounters(rows)
    coverage = [sum(any(r.teacher == y for r in group) for group in groups) for y in (0, 1)]
    record["encounters_by_class"] = coverage
    if min(coverage) < 2:
        return dict(record, decision="insufficient_fresh_encounters")
    old = (load_weights(folder, incumbent).predict if incumbent else
           lambda x: previous["majority"])
    reference = policy.confusion(rows, old)
    trial = policy.confusion(rows, load_weights(folder, candidate).predict)
    record.update(reference=reference, trial=trial, reference_kind="incumbent" if incumbent else "training_majority")
    new_recall = trial["recall_by_class"]
    if incumbent:
        keep = (trial["balanced_accuracy"] >= reference["balanced_accuracy"] + .02
                and all(n + .05 >= o for n, o in zip(new_recall, reference["recall_by_class"])))
    else:
        keep = min(new_recall) >= .5 and trial["balanced_accuracy"] >= reference["balanced_accuracy"] + .05
    if keep:
        record["practice"] = candidate
    return dict(record, decision="use_for_practice" if keep else "retain_incumbent")


def training_cells(design, include_extension):
    cells = design["training"] + (design.get("training_extension", []) if include_extension else []) + design.get("stream_training", [])
    names = [c["name"] for c in cells]
    policy.require(len(names) == len(set(names)) and all(n and Path(n).name == n and n not in (".", "..") and "\\" not in n for n in names),
                   "Expected unique training directory names")
    policy.require(not set(names).intersection(c["name"] for c in design.get("test", [])),
                   "A scored test cannot enter the training stream")
    return cells


def sync(runs, schedule, state, include_extension=False):
    """Consume the contiguous completed prefix. A saved match can never be re-labelled."""
    cells = training_cells(json.loads(schedule.read_bytes()), include_extension)
    names = [c["name"] for c in cells]
    state.mkdir(parents=True, exist_ok=True)
    (state / "weights").mkdir(exist_ok=True)
    path = state / "history.json"
    with writer(state):
        history = json.loads(path.read_bytes()) if path.exists() else {"schema": 1, "matches": []}
        old = history["matches"]
        policy.require([x["name"] for x in old] == names[:len(old)], "Training history changed; use append-only scheduling")
        batches = []
        seen_logs = set()
        for i, cell in enumerate(cells):
            directory = runs / cell["name"]
            receipt = directory / "receipt.json"
            if not receipt.is_file():
                policy.require(i >= len(old), "Missing retained match")
                break
            receipt_bytes = receipt.read_bytes()
            receipt_hash = sha(receipt_bytes)
            run = json.loads(receipt_bytes)
            if i >= len(old) and run.get("status") == "failed":
                break
            policy.require(run.get("kind") == "adjoin-arena-stock-red-policy" and run.get("status") == "live_join_and_loadout_verified"
                           and run["requested_map"] == cell["map"] and run["red_policy"]["elite"]
                           and "start_and_outcomes" in run["red_policy"], "Expected completed ungated Red match")
            build_info = run["red_policy"]["build"]
            policy.require(build_info["red_commit"] == "f453778a3cf670dea43c44315786ae4afc8ae440",
                           "Unexpected Red teacher revision")
            build = build_info["binary_sha256"]
            policy.require(not old or old[0]["build"] == build, "Teacher build changed inside the learning stream")
            rows, hashes = policy.read_match(runs, cell)
            policy.require(all(hashes[s] == run["log_sha256"][s + ".log"] for s in hashes), "Owner log hash mismatch")
            policy.require(not seen_logs.intersection(hashes.values()), "Duplicated training logs")
            seen_logs.update(hashes.values())
            learned_seat = run["red_policy"]["model_side"]
            rows = [row for row in rows if row.seat != learned_seat]
            policy.require(all(row.model == "teacher" and row.selected == row.teacher for row in rows),
                           "Training observations must come from Red controlling that seat")
            batches.append(rows)
            if i < len(old):
                policy.require(receipt_hash == old[i]["receipt_sha256"] and hashes == old[i]["logs"],
                               "Training evidence changed after checkpoint")
                continue
            assessment = check_challenger(state, history, rows)
            counts = [sum(r.teacher == label for batch in batches for r in batch) for label in (0, 1)]
            key = None
            if min(counts):
                data = policy.fit(policy.weighted_rows(batches)).encode()
                key = sha(data)
                weight_path = state / "weights" / (key + ".weights")
                if weight_path.exists():
                    policy.require(weight_path.read_bytes() == data, "Existing weights differ")
                else:
                    atomic_write(weight_path, data)
            old.append(dict(name=cell["name"], receipt_sha256=receipt_hash, logs=hashes, build=build,
                            eligible_teacher_ticks=len(rows), cumulative_classes=counts,
                            majority=int(counts[1] > counts[0]), candidate=key,
                            practice=assessment["practice"], fresh_match_check=assessment))
            atomic_write(path, (json.dumps(history, indent=2) + "\n").encode())
        return history


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=Path)
    parser.add_argument("--schedule", type=Path)
    parser.add_argument("--state", required=True, type=Path, help="External directory for atomic snapshots and immutable weights")
    parser.add_argument("--next-practice", action="store_true", help="Print selected weights path, or 'teacher' before qualification")
    parser.add_argument("--include-extension", action="store_true")
    parser.add_argument("--follow", action="store_true", help="Watch for new completed training matches until interrupted")
    parser.add_argument("--finish-batch", action="store_true", help="Exit once all currently scheduled training matches are processed")
    parser.add_argument("--interval", type=float, default=10)
    args = parser.parse_args()
    if args.next_practice:
        history = args.state / "history.json"
        matches = json.loads(history.read_bytes())["matches"] if history.is_file() else []
        key = matches[-1]["practice"] if matches else None
        if key:
            load_weights(args.state, key)
        print((args.state / "weights" / (key + ".weights")).resolve() if key else "teacher")
        return
    if args.runs is None or args.schedule is None:
        parser.error("updating the stream requires --runs and --schedule")
    if not math.isfinite(args.interval) or args.interval < 1:
        parser.error("--interval must be at least one second")
    count = -1
    signature = None
    while True:
        schedule_data = args.schedule.read_bytes()
        cells = training_cells(json.loads(schedule_data), args.include_extension)
        paths = [args.runs / cell["name"] / "receipt.json" for cell in cells]
        current = (sha(schedule_data), [(p.stat().st_mtime_ns, p.stat().st_size) if p.is_file() else None for p in paths])
        if signature != current:
            h = sync(args.runs, args.schedule, args.state, args.include_extension)
            signature = current
            if len(h["matches"]) != count:
                count = len(h["matches"])
                last = h["matches"][-1] if count else {}
                print(json.dumps({"matches": count, "candidate": last.get("candidate"), "practice": last.get("practice")}), flush=True)
        if not args.follow or (args.finish_batch and count == len(cells)):
            break
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
