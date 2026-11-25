"""Fit and audit Red's pickup-versus-engage policy from native BOT_DUEL decisions.

Only eligible Red arbitration events are examples. Labels come from the native
teacher branch. The portable neural network uses integer arithmetic in C
and Python. A prediction of 1 pursues the stock pickup and permits simultaneous
aim/fire. A prediction of 0 releases the legs to combat.
"""
import argparse
from collections import Counter
from dataclasses import dataclass, replace
import hashlib
import gzip
import json
import math
from pathlib import Path
import re


FEATURES = ("health", "shields", "enemy_mm", "item_mm", "weapon", "ammo",
            "pack", "wet", "remaining_route_nodes")
SEATS = ("dark", "light")
HIDDEN = 8
Q = 1024
EPOCHS = 320
TRAIN_SEED = 20261125
ENCOUNTER_GAP_SECONDS = 0.6
FIELD = re.compile(r"(?:^|\s)([A-Za-z][A-Za-z0-9_]*)=")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def fields(line):
    keys = list(FIELD.finditer(line))
    return {entry[1]: line[entry.end():keys[i+1].start() if i+1 < len(keys)
                          else len(line)].strip() for i, entry in enumerate(keys)}


@dataclass(frozen=True)
class Decision:
    seat: str
    life: int
    seq: int
    time: float
    target: int
    item: int
    x: tuple
    teacher: int
    selected: int
    applied: int
    owner: str
    model: str
    firing: bool
    moving: bool
    forward: float = 0.
    slide: float = 0.
    read_forward: float | None = None
    read_slide: float | None = None


def decision(line, seat):
    f = fields(line)
    x = tuple(int(n) for n in f["f"].split(","))
    require(len(x) == len(FEATURES), "Wrong feature vector length")
    require(x[6] in (0, 1) and x[7] in (0, 1), "Invalid binary feature")
    labels = [int(f[key]) for key in ("teacher", "selected", "applied", "fire1", "fire2")]
    require(all(n in (0, 1) for n in labels), "Invalid class or control bit")
    t = float(f["t"])
    require(math.isfinite(t), "Invalid game time")
    forward, slide = float(f["forward"]), float(f["slide"])
    require(math.isfinite(forward) and math.isfinite(slide), "Invalid applied movement")
    return Decision(seat, int(f["life"]), int(f["seq"]), t,
                    int(f["target"]), int(f["item"]), x, *labels[:3],
                    f["owner"], f["model"], bool(labels[3] or labels[4]),
                    bool(abs(forward) > 1e-6 or abs(slide) > 1e-6), forward, slide)


def read_match(root, match):
    rows = []
    hashes = {}
    for seat in SEATS:
        path = root / match["name"] / (seat + ".log")
        previous = None
        samples, reads = {}, {}
        hashes[seat] = digest(path)
        with path.open(encoding="utf-8", errors="replace") as stream:
            for n, line in enumerate(stream, start=1):
                if line.startswith("BOT_RED_READ "):
                    f = fields(line)
                    key = int(f["life"]), int(f["seq"])
                    axis = f["axis"]
                    require(axis in ("forward", "slide"), f"{path}:{n}: unknown engine axis")
                    axes = reads.setdefault(key, {})
                    require(axis not in axes, f"{path}:{n}: duplicated engine axis read")
                    axes[axis] = float(f["value"])
                    continue
                if not line.startswith("BOT_DUEL "):
                    continue
                try:
                    row = decision(line.split("BOT_DUEL ", 1)[1], seat)
                    require(previous is None or row.seq > previous.seq,
                            "Duplicate or out-of-order decision sequence")
                except (KeyError, ValueError) as exc:
                    raise ValueError(f"{path}:{n}: {exc}") from exc
                previous = row
                samples[row.life, row.seq] = row
        require(set(reads) <= set(samples), f"{path}: engine read with no matching decision")
        for key, row in samples.items():
            axes = reads.get(key, {})
            require(all(value == getattr(row, axis) for axis, value in axes.items()),
                    f"{path}: delivered axis differs from selected frame at life/seq {key}")
            rows.append(replace(row, read_forward=axes.get("forward"), read_slide=axes.get("slide")))
    return rows, hashes


def encounters(rows):
    result = []
    previous = None
    for row in rows:
        if (previous is None or row.seat != previous.seat or row.life != previous.life
                or row.target != previous.target or row.item != previous.item
                or not 0 <= row.time - previous.time <= ENCOUNTER_GAP_SECONDS):
            result.append([])
        result[-1].append(row)
        previous = row
    return result


def weighted_rows(matches):
    """Equal mass per nonempty match, encounter and unique (features, label) pair."""
    return weighted_examples([[[(r.x, r.teacher) for r in group] for group in encounters(rows)]
                              for rows in matches])


def weighted_examples(match_groups):
    points = Counter()
    for groups in match_groups:
        for group in groups:
            unique = set(group)
            weight = 1 / (len(groups) * len(unique))
            for key in sorted(unique):
                points[key] += weight
    return [(x, y, w) for (x, y), w in sorted(points.items())]


def fixed_input(value, center, scale):
    delta = (value - center) * Q
    scaled = (abs(delta) // scale) * (-1 if delta < 0 else 1)
    return max(-2*Q, min(2*Q, scaled))


@dataclass(frozen=True)
class Model:
    centers: tuple
    scales: tuple
    hidden: tuple
    output: tuple

    def logit(self, x):
        z = [fixed_input(v, c, s) for v, c, s in zip(x, self.centers, self.scales, strict=True)]
        h = []
        for bias, *weights in self.hidden:
            acc = bias + sum(w * v for w, v in zip(weights, z))
            h.append(max(0, min(32*Q, acc // Q)))
        return self.output[0] + sum(w * v for w, v in zip(self.output[1:], h))

    def predict(self, x):
        return int(self.logit(x) >= 0)

    def encode(self):
        lines = [f"RED_NEURAL_V1 {len(FEATURES)} {HIDDEN}"]
        for row in (self.centers, self.scales, *self.hidden, self.output):
            lines.append(" ".join(map(str, row)))
        return ("\n".join(lines) + "\n").encode("ascii")

    @classmethod
    def decode(cls, data):
        lines = data.decode("ascii").splitlines()
        require(lines[0] == f"RED_NEURAL_V1 {len(FEATURES)} {HIDDEN}" and len(lines) == HIDDEN + 4,
                "Incompatible neural model")
        centers, scales, *layers = (tuple(map(int, row.split())) for row in lines[1:])
        require(len(centers) == len(scales) == len(FEATURES) and all(abs(c) <= 2**30 for c in centers)
                and all(1 <= s <= 2**30 for s in scales), "Invalid normalization")
        hidden, output = layers[:-1], layers[-1]
        require(all(len(row) == len(FEATURES)+1 for row in hidden) and len(output) == HIDDEN+1,
                "Invalid neural dimensions")
        require(all(abs(r[0]) <= 32*Q*Q and all(abs(w) <= 16*Q for w in r[1:]) for r in layers),
                "Out-of-range neural weights")
        return cls(centers, scales, tuple(hidden), output)


def fit(points):
    """Full-batch Adam on native teacher labels; fixed budget, zero fit-time holdout access."""
    import numpy as np

    totals = [sum(w for _, label, w in points if label == y) for y in (0, 1)]
    require(all(t > 0 for t in totals), "Both native teacher classes required")
    raw = np.asarray([list(point) for point, _, _ in points], dtype=np.float64)
    labels = np.asarray([label for _, label, _ in points])
    weight = np.asarray([mass / (2*totals[label]) for _, label, mass in points])
    centers = np.rint(np.einsum("n,nj->j", weight, raw)).astype(np.int64)
    scales = np.maximum(1, np.rint(np.sqrt(np.einsum("n,nj->j", weight, (raw-centers)**2)))).astype(np.int64)
    x = np.clip(np.trunc((raw-centers)*Q/scales), -2*Q, 2*Q) / Q
    rng = np.random.Generator(np.random.PCG64(TRAIN_SEED))
    w1 = rng.normal(0, .28, (len(FEATURES), HIDDEN))
    b1 = np.full(HIDDEN, .15)
    w2 = rng.normal(0, .18, HIDDEN)
    b2 = np.asarray(0.)
    params = (w1, b1, w2, b2)
    first, second = [[np.zeros_like(p) for p in params] for _ in range(2)]
    for epoch in range(1, EPOCHS+1):
        # Avoid dependency on BLAS kernel selection and thread reduction order.
        pre = np.einsum("ni,ih->nh", x, w1, optimize=False) + b1
        hidden = np.clip(pre, 0., 32.)
        logit = np.einsum("nh,h->n", hidden, w2, optimize=False) + b2
        probability = 1 / (1 + np.exp(-np.clip(logit, -50., 50.)))
        err = weight * (probability - labels)
        back = (err[:, None] * w2) * ((pre > 0) & (pre < 32))
        gradients = (np.einsum("ni,nh->ih", x, back, optimize=False) + .0001*w1,
                     back.sum(axis=0), np.einsum("n,nh->h", err, hidden, optimize=False) + .0001*w2,
                     err.sum())
        for p, m, v, g in zip(params, first, second, gradients):
            m *= .9
            m += .1*g
            v *= .999
            v += .001*g*g
            p -= .025*(m/(1-.9**epoch)) / (np.sqrt(v/(1-.999**epoch)) + 1e-8)
            np.clip(p, -15., 15., out=p)

    def layer(bias, weights):
        return (round(float(bias)*Q*Q), *(int(n) for n in np.rint(weights*Q)))
    model = Model(tuple(map(int, centers)), tuple(map(int, scales)),
                  tuple(layer(b1[k], w1[:, k]) for k in range(HIDDEN)), layer(b2, w2))
    return Model.decode(model.encode())


def confusion(rows, predict):
    counts = [[0, 0], [0, 0]]
    for row in rows:
        counts[row.teacher][predict(row.x)] += 1
    recalls = [cells[i] / sum(cells) if sum(cells) else None for i, cells in enumerate(counts)]
    n = sum(map(sum, counts))
    return {"matrix": counts, "accuracy": (counts[0][0]+counts[1][1]) / n if n else None,
            "recall_by_class": recalls,
            "balanced_accuracy": sum(recalls)/2 if None not in recalls else None}


def weighted_accuracy(rows, predict):
    groups = encounters(rows)
    if not groups:
        return None
    accuracies = []
    for group in groups:
        unique = {(r.x, r.teacher) for r in group}
        accuracies.append(sum(predict(x) == y for x, y in unique) / len(unique))
    return sum(accuracies) / len(accuracies)


def support(rows):
    return [sum(r.teacher == y for r in rows) for y in (0, 1)]


def applied_class(row):
    # The binary wire 'applied' means 'supply won'. Its zero also covers traps,
    # stationary ticks and overrides, so an engage requires the movement owner.
    if row.owner == "supply" and row.applied == 1 and row.moving:
        return 1
    if row.owner == "engage" and row.applied == 0 and row.moving:
        return 0
    return None


def delivered_class(row):
    witnessed = ((row.read_forward is not None and abs(row.read_forward) > 1e-6)
                 or (row.read_slide is not None and abs(row.read_slide) > 1e-6))
    return applied_class(row) if witnessed else None


def source_summary(rows, hashes):
    return {"raw_sha256_by_seat": hashes, "n_decisions": len(rows),
            "encounters": len(encounters(rows)), "teacher_support": support(rows),
            "teacher_selected": sum(r.teacher == r.selected for r in rows),
            "selected_applied": sum(applied_class(r) == r.selected for r in rows),
            "selected_with_engine_read": [sum(r.selected == y and delivered_class(r) == y for r in rows)
                                          for y in (0, 1)],
            "owners": dict(Counter(r.owner for r in rows)),
            "applied_pickup_moving": sum(r.applied and r.moving for r in rows),
            "applied_pickup_with_fire": sum(r.applied and r.firing for r in rows)}


def checked_receipt(root, match, hashes, expected_scope):
    path = root / match["name"] / "receipt.json"
    evidence = json.loads(path.read_bytes())
    require(evidence.get("kind") in ("adjoin-arena-stock-red-policy", "adjoin-arena-mode-transfer") and
            evidence.get("status") == "live_join_and_loadout_verified", f"{path}: incomplete native match")
    if evidence["kind"] == "adjoin-arena-stock-red-policy":
        require(evidence.get("observer_status") == "recorded", f"{path}: missing primary observer")
    require(evidence["requested_map"] == match["map"] and
            all(evidence["log_sha256"][seat+".log"] == sha for seat, sha in hashes.items()),
            f"{path}: raw log or map differs")
    red = evidence["red_policy"]
    require(red["model_side"] == (match["subject"] if match["controller"] == "model" else None),
            f"{path}: wrong controlled seat")
    level_key = "jkl/" + str(match["map"]).lower()
    level_sha = evidence["sha256"][level_key]
    scope = "ffa/guns/force"
    if evidence["kind"] == "adjoin-arena-mode-transfer":
        mode = evidence["mode_transfer"]
        verify_transfer_match(evidence, match, path)
        weapons = "sabers" if mode["weapons"] == "saber" else mode["weapons"]
        require(mode["force"] in ("on", "off") and mode["content"]["map_sha256"] == level_sha,
                f"{path}: unverified rules or level content")
        scope = f"{mode['mode']}/{weapons}/" + ("force" if mode["force"] == "on" else "noforce")
    require(scope == expected_scope, f"{path}: wrong mode/rules")
    require(scope.split("/")[0] in ("ffa", "tdm") and scope.split("/")[1] == "guns",
            f"{path}: no gear-model target for this mode")
    return digest(path), red, level_sha


def verify_transfer_match(evidence, match, path):
    """Mode-transfer trials can use native clock and control receipts without a camera."""
    mode = evidence["mode_transfer"]
    require(evidence.get("observer_status") in (None, "recorded") and
            mode["native"]["qualification_errors"] == [], f"{path}: failed native or observer verification")
    require(mode["content"]["map_sha256"] == match["map_sha256"], f"{path}: unexpected transfer map digest")
    outcomes = evidence["red_policy"]["start_and_outcomes"]
    pace = evidence["pace_experiment"]
    require(outcomes["first_seat_move_before_second_join_wall_s"] > 0 and
            set(pace["roles"]) == {"host", *SEATS} and
            all(role["observed_rate"] > 0 for role in pace["roles"].values()) and
            pace["requested_game_seconds"] == match["game_seconds"] and
            digest(path.parent / "pace-trace.jsonl") == pace["trace_sha256"], f"{path}: incomplete clock or opening")
    for seat in SEATS:
        owner = outcomes["owners"][seat]
        require("BOT_RED_JOIN" in owner["events"] and "BOT_RED_FIRST" in owner["events"] and
                any(abs(float(cmd["fwd"])) + abs(float(cmd["slide"])) > 0
                    for cmd in owner["first_movement_by_life"]) and mode["native"]["owners"][seat]["movement_seen"],
                f"{path}: missing native control evidence for {seat}")


def load_teacher(root, schedule, rules_scope="ffa/guns/force"):
    raw, sources = {}, {}
    seen = set()
    for match in schedule:
        name = match["name"]
        rows, hashes = read_match(root, match)
        require(len(set(hashes.values())) == len(hashes) and not seen.intersection(hashes.values()),
                f"{name}: duplicated training logs")
        seen.update(hashes.values())
        require(all(r.model == "teacher" and r.selected == r.teacher for r in rows),
                f"{name}: teacher provenance or selected label mismatch")
        raw[name], sources[name] = rows, source_summary(rows, hashes)
        sha, red, level_sha = checked_receipt(root, match, hashes, rules_scope)
        require(red["weights_sha256"] is None, f"{name}: unexpected loaded model")
        sources[name]["run_receipt_sha256"] = sha
        sources[name]["map_sha256"] = level_sha
    return raw, sources


def extension_needed(matches):
    counts = [support(rows) for rows in matches]
    return any(sum(c[y] for c in counts) < 20 or sum(c[y] > 0 for c in counts) < 2
               for y in (0, 1))


def write_corpus(path, raw, sources, schedule_sha):
    """Chronological eligible training rows, stripped of identity, text and filesystem paths."""
    columns = ["encounter", "seat", "life", "sequence", "game_seconds", "target", "item",
               *FEATURES, "native_teacher", "selected", "applied", "firing", "moving"]
    matches = {}
    for name, rows in raw.items():
        data = []
        for k, group in enumerate(encounters(rows)):
            for r in group:
                data.append([k, r.seat, r.life, r.seq, r.time, r.target, r.item,
                             *r.x, r.teacher, r.selected, r.applied, int(r.firing), int(r.moving)])
        matches[name] = {"raw_sha256_by_seat": sources[name]["raw_sha256_by_seat"], "rows": data}
    doc = {"schema": 1, "source": "Native Red teacher BOT_DUEL, whole training matches only",
           "schedule_sha256": schedule_sha, "columns": columns, "matches": matches}
    content = json.dumps(doc, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as raw_file:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw_file, mtime=0) as compressed:
            compressed.write(content)


def rebuild(args):
    freeze = json.loads(args.train_receipt.read_text(encoding="utf-8"))
    require(digest(args.corpus) == freeze["corpus_sha256"], "Corrupt or different corpus")
    with gzip.open(args.corpus, "rt", encoding="ascii") as stream:
        corpus = json.load(stream)
    require(list(corpus["matches"]) == freeze["training_matches"] and
            corpus["schedule_sha256"] == freeze["training_schedule_sha256"], "Unexpected match split")
    columns = corpus["columns"]
    x_ids = [columns.index(key) for key in FEATURES]
    group_id = columns.index("encounter")
    label_id = columns.index("native_teacher")
    play_id = columns.index("selected")
    matches = []
    for name, entry in corpus["matches"].items():
        require(entry["raw_sha256_by_seat"] == freeze["training"][name]["raw_sha256_by_seat"]
                and len(entry["rows"]) == freeze["training"][name]["n_decisions"], "Wrong raw provenance")
        groups = {}
        for row in entry["rows"]:
            label = row[label_id]
            require(label in (0, 1) and row[play_id] == label, "Invalid teacher row")
            groups.setdefault(row[group_id], []).append((tuple(row[i] for i in x_ids), label))
        matches.append(groups.values())
    data = fit(weighted_examples(matches)).encode()
    require(hashlib.sha256(data).hexdigest() == freeze["weights_sha256"], "Model reconstruction differed")
    save_frozen_weights(args.model, data)
    return {"same_frozen_weights": True, "sha256": freeze["weights_sha256"]}


def save_frozen_weights(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        require(path.read_bytes() == data, "Refusing to replace a different frozen model")
    else:
        path.write_bytes(data)


def train(args, schedule):
    scope = schedule.get("rules_scope", "ffa/guns/force")
    raw, sources = load_teacher(args.runs, schedule["training"], scope)
    extend = extension_needed(raw.values())
    if args.status:
        return {"training": sources, "extension_needed": extend}
    if extend:
        extra, info = load_teacher(args.runs, schedule["training_extension"], scope)
        initial_sha = {sha for report in sources.values() for sha in report["raw_sha256_by_seat"].values()}
        extra_sha = {sha for report in info.values() for sha in report["raw_sha256_by_seat"].values()}
        require(not initial_sha.intersection(extra_sha), "Extension reused a base training log")
        raw.update(extra)
        sources.update(info)
    require(not extension_needed(raw.values()), "Native class support rule failed even after extension")
    model = fit(weighted_rows(raw.values()))
    weights = model.encode()
    from importlib.metadata import version
    import platform
    all_rows = [row for rows in raw.values() for row in rows]
    counts = support(all_rows)
    majority = int(counts[1] > counts[0])
    save_frozen_weights(args.model, weights)
    write_corpus(args.corpus, raw, sources, digest(args.schedule))
    return {"schema": 1, "teacher_revision": schedule["teacher_revision"],
            "rules_scope": scope,
            "python": platform.python_version(), "numpy": version("numpy"),
            "training_schedule_sha256": digest(args.schedule), "trainer_sha256": digest(Path(__file__)),
            "feature_order": FEATURES, "classes": ["engage", "pursue_pickup"], "training": sources,
            "used_extension": extend, "training_support": counts, "training_majority": majority,
            "training_confusion": confusion(all_rows, model.predict), "training_matches": list(raw),
            "weights_sha256": hashlib.sha256(weights).hexdigest(), "architecture": [len(FEATURES), HIDDEN, 1], "learned_parameters": 89,
            "corpus_sha256": digest(args.corpus),
            "method": "Equal match and encounter weight; duplicate feature-label pairs collapse within "
                      "an encounter. Class-balanced cross entropy, NumPy float64 Adam, 320 fixed full-batch steps, "
                      "learning rate 0.025, L2 0.0001 on weights, PCG64 seed 20261125 and quantized ReLU inference."}


def evaluate(args, schedule):
    receipt = json.loads(args.train_receipt.read_text(encoding="utf-8"))
    require(receipt["training_schedule_sha256"] == digest(args.schedule), "Schedule differs from freeze")
    scope = schedule.get("rules_scope", "ffa/guns/force")
    require(receipt["rules_scope"] == scope, "Scope differs from training")
    model = Model.decode(args.model.read_bytes())
    key = digest(args.model)
    require(receipt["weights_sha256"] == key, "Weights differ from freeze")
    majority = lambda _x: receipt["training_majority"]
    # The source teacher gates this narrow opportunity at 0.45 world units.
    # Exported milliworld-unit observations round distance before this check.
    scripted_range = lambda x: int(x[2] >= 450)
    blocked_names = set(receipt["training_matches"])
    blocked_hashes = {sha for entry in receipt["training"].values()
                      for sha in entry["raw_sha256_by_seat"].values()}
    controls, live, summaries, by_map, witnesses = [], [], {}, {}, {}
    outcomes = {}
    for match in schedule["test"]:
        name = match["name"]
        rows, hashes = read_match(args.runs, match)
        require(name not in blocked_names and not set(hashes.values()) & blocked_hashes,
                f"{name}: data overlaps training or duplicates another held-out log")
        blocked_names.add(name)
        blocked_hashes.update(hashes.values())
        subject = [r for r in rows if r.seat == match["subject"]]
        deployed = [r for r in rows if r.model == key]
        require(all(r.seat == match["subject"] and match["controller"] == "model" for r in deployed),
                f"{name}: unexpected learned owner")
        require(all(r.model in (key, "teacher") for r in rows), f"{name}: unknown model source")
        require(all(model.predict(r.x) == r.selected for r in deployed),
                f"{name}: native decision disagrees with exported weights")
        summary = source_summary(rows, hashes)
        stamp, red, level_sha = checked_receipt(args.runs, match, hashes, scope)
        require(red["weights_sha256"] == (key if match["controller"] == "model" else None),
                f"{name}: mismatched loaded weights")
        summary["run_receipt_sha256"] = stamp
        summary["map_sha256"] = level_sha
        summary.update(controller=match["controller"], subject=match["subject"], map=match["map"],
                       pair=match["pair"], subject_decisions=len(subject))
        sides = red["start_and_outcomes"]["owners"]
        arm = {}
        for side in SEATS:
            state = sides[side]["owner_state"]
            arm[side] = {"kill_increments": state["kill_increments"], "death_increments": state["death_increments"],
                         "weapon_bin_gains": [g["bin"] for g in state["weapon_gains"]],
                         "health_loss": state["health_loss"], "shield_loss": state["shield_loss"],
                         "last_state_kills": state["last_state"]["kills"], "last_state_deaths": state["last_state"]["deaths"]}
        outcomes.setdefault(match["pair"], {"map": match["map"], "subject": match["subject"]})[match["controller"]] = arm
        if match["controller"] == "teacher":
            require(all(r.model == "teacher" and r.selected == r.teacher for r in rows),
                    f"{name}: contaminated script-control match")
            controls.extend(rows)
            by_map.setdefault(match["map"], []).extend(rows)
            summary["offline_candidate"] = confusion(rows, model.predict)
            summary["offline_majority"] = confusion(rows, majority)
            summary["mean_encounter_accuracy"] = weighted_accuracy(rows, model.predict)
            summary["mean_encounter_majority_accuracy"] = weighted_accuracy(rows, majority)
        else:
            live.extend(deployed)
            summary["model_decisions"] = len(deployed)
            summary["subject_teacher_fallbacks"] = len(subject) - len(deployed)
            summary["model_selected"] = [sum(r.selected == y for r in deployed) for y in (0, 1)]
            summary["model_selected_and_applied"] = [sum(r.selected == y and applied_class(r) == y for r in deployed)
                                                     for y in (0, 1)]
            summary["model_movement_owners"] = dict(Counter(r.owner for r in deployed))
            summary["model_selected_with_engine_read"] = [sum(r.selected == y and delivered_class(r) == y
                                                              for r in deployed) for y in (0, 1)]
            for row in deployed:
                y = delivered_class(row)
                if y == row.selected and y not in witnesses:
                    witnesses[y] = dict(match=name, seat=row.seat, life=row.life, decision_seq=row.seq,
                                        game_seconds=row.time, inputs=list(row.x), native_teacher=row.teacher,
                                        selected=row.selected, owner=row.owner, forward=row.forward, slide=row.slide,
                                        read_forward=row.read_forward, read_slide=row.read_slide, fire=row.firing,
                                        raw_log_sha256=hashes[row.seat])
            summary["applied_pickup_with_fire"] = sum(r.applied and r.firing for r in deployed)
            summary["model_vs_shadow_teacher"] = confusion(deployed, model.predict)
            summary["model_disagreed_with_shadow_teacher"] = sum(r.teacher != r.selected for r in deployed)
        summaries[name] = summary
    applied = [sum(r.selected == y and applied_class(r) == y for r in live) for y in (0, 1)]
    read = [sum(r.selected == y and delivered_class(r) == y for r in live) for y in (0, 1)]
    return {"schema": 1, "rules_scope": scope, "schedule_sha256": digest(args.schedule), "weights_sha256": key,
            "classes": receipt["classes"], "interpretation": "Confusion rows are native shadow labels, "
            "columns are predictions. These ticks are correlated. Different matches use fresh stock spawns.",
            "matches": summaries, "paired_owner_outcomes": outcomes, "offline_teacher_control_decisions": len(controls),
            "offline_candidate": confusion(controls, model.predict), "offline_training_majority": confusion(controls, majority),
            "offline_known_range_rule_450": confusion(controls, scripted_range),
            "offline_by_map": {key: {"candidate": confusion(value, model.predict),
                                    "training_majority": confusion(value, majority)}
                               for key, value in by_map.items()},
            "n_live_model_decisions": len(live), "live_model_vs_shadow": confusion(live, model.predict),
            "live_model_selected": [sum(r.selected == y for r in live) for y in (0, 1)],
            "live_model_selected_and_applied": applied, "model_selected_with_engine_read": read,
            "live_model_selected_with_engine_read": read, "native_engine_witnesses": witnesses,
            "both_live_actions_verified": all(read)}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=("train", "evaluate", "rebuild"))
    p.add_argument("--runs", type=Path)
    p.add_argument("--schedule", type=Path)
    p.add_argument("--model", type=Path)
    p.add_argument("--corpus", type=Path)
    p.add_argument("--receipt", type=Path)
    p.add_argument("--train-receipt", type=Path)
    p.add_argument("--status", action="store_true", help="Read original training support only")
    a = p.parse_args()
    if not a.status and not a.model:
        p.error("--model is required")
    if a.action != "train" and (not a.train_receipt or a.status):
        p.error("evaluate/rebuild require --train-receipt and exclude --status")
    if a.action != "evaluate" and not (a.status or a.corpus):
        p.error("train/rebuild require --corpus")
    if a.action == "rebuild":
        result = rebuild(a)
    else:
        if not (a.runs and a.schedule):
            p.error("train/evaluate require --runs and --schedule")
        schedule = json.loads(a.schedule.read_text(encoding="utf-8-sig"))
        result = train(a, schedule) if a.action == "train" else evaluate(a, schedule)
    output = json.dumps(result, indent=2) + "\n"
    if a.receipt:
        a.receipt.parent.mkdir(parents=True, exist_ok=True)
        a.receipt.write_bytes(output.encode("utf-8"))
    else:
        print(output, end="")


if __name__ == "__main__":
    main()
