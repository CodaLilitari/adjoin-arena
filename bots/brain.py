"""Persistent per-profile BrainStore: decisions, map edges, models.

One local store that survives matches and processes:

* decision ledger - teacher/selected/outcome rows for distillation;
* edge statistics - persistent directed-edge attempts per level digest
  and rules scope, generalising the native nav-recall penalties;
* model registry - hash-addressed candidate weights with gated
  promotion and rollback (safety + held-out evidence required).

Offline training (NumPy) fits a small global edge model here; live play
only appends evidence and reads already-qualified artifacts. Nothing in
this module sends a game command.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sqlite3
import time
from pathlib import Path

SCHEMA = 1
EDGE_FEATURES = ("distance", "dz", "abs_dz", "mode", "from_water", "to_water",
                 "dest_item", "base_cost", "degree_from", "degree_to")
_NAV_LEARN = re.compile(
    r"BOT_NAV_LEARN .*event=(stall|arrive) .*from_key=([0-9a-fA-F]+) "
    r"to_key=([0-9a-fA-F]+) edge=(\d+)")
_EDGE_ATTEMPT = re.compile(
    r"BOT_EDGE_ATTEMPT .*event=(stall|arrive) from_key=([0-9a-fA-F]+) "
    r"to_key=([0-9a-fA-F]+) edge=(\d+) dist_mm=(-?\d+) dz_mm=(-?\d+) "
    r"from_water=([01]) to_water=([01]) dest_item=([01]) "
    r"base_cost_milli=(-?\d+) degree_from=(\d+) degree_to=(\d+)")


def _packed(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _finite_number(value, what: str) -> float:
    if type(value) is bool or not isinstance(value, (int, float)):
        raise ValueError(f"{what} must be a number.")
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"{what} must be finite.")
    return value


class BrainStore:
    """SQLite evidence plus a JSON manifest of hash-addressed models."""

    def __init__(self, root: Path, profile: str):
        if not profile or "/" in profile or "\\" in profile:
            raise ValueError("Brain profile must be a plain name.")
        self.root = Path(root)
        self.profile = profile
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "models").mkdir(exist_ok=True)
        self.db = sqlite3.connect(self.root / "brain.sqlite3", timeout=5)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS decisions (
                id INTEGER PRIMARY KEY, ts REAL NOT NULL, kind TEXT NOT NULL,
                map_sha TEXT NOT NULL, scope TEXT NOT NULL, policy_hash TEXT NOT NULL,
                pace TEXT NOT NULL DEFAULT 'unknown', build TEXT NOT NULL DEFAULT '',
                features TEXT NOT NULL, candidates TEXT, teacher INTEGER,
                selected INTEGER, applied INTEGER, outcome TEXT
            );
            CREATE INDEX IF NOT EXISTS decisions_kind ON decisions(kind);
            CREATE TABLE IF NOT EXISTS edge_stats (
                map_sha TEXT NOT NULL, scope TEXT NOT NULL, pace TEXT NOT NULL DEFAULT 'unknown',
                from_key TEXT NOT NULL, to_key TEXT NOT NULL, mode INTEGER NOT NULL,
                attempts INTEGER NOT NULL, successes INTEGER NOT NULL,
                failures INTEGER NOT NULL, time_sum REAL NOT NULL,
                time_sq REAL NOT NULL, damage_sum REAL NOT NULL,
                last_seen REAL NOT NULL, features TEXT,
                PRIMARY KEY (map_sha, scope, pace, from_key, to_key, mode)
            );
            CREATE TABLE IF NOT EXISTS coach_arms (
                label TEXT NOT NULL, build TEXT NOT NULL, arm TEXT NOT NULL,
                plays INTEGER NOT NULL, total REAL NOT NULL,
                PRIMARY KEY (label, build, arm)
            );
        """)
        self._migrate_pace_columns()
        self.manifest_path = self.root / "manifest.json"
        if self.manifest_path.is_file():
            self.manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            if self.manifest.get("profile") != profile:
                raise ValueError("Brain root belongs to a different profile.")
        else:
            self.manifest = {"schema": SCHEMA, "profile": profile,
                             "created_at": time.time(), "active": {},
                             "history": [], "models": []}
            self._save_manifest()

    def _migrate_pace_columns(self) -> None:
        """Add pace provenance to stores created before it existed."""
        cols = {row[1] for row in self.db.execute("PRAGMA table_info(decisions)")}
        with self.db:
            if "pace" not in cols:
                self.db.execute("ALTER TABLE decisions ADD COLUMN pace TEXT NOT NULL DEFAULT 'unknown'")
            if "build" not in cols:
                self.db.execute("ALTER TABLE decisions ADD COLUMN build TEXT NOT NULL DEFAULT ''")
            edge_cols = {row[1] for row in self.db.execute("PRAGMA table_info(edge_stats)")}
            if "pace" not in edge_cols:
                self.db.execute(
                    "CREATE TABLE edge_stats_v2 ("
                    "map_sha TEXT NOT NULL, scope TEXT NOT NULL, pace TEXT NOT NULL DEFAULT 'unknown', "
                    "from_key TEXT NOT NULL, to_key TEXT NOT NULL, mode INTEGER NOT NULL, "
                    "attempts INTEGER NOT NULL, successes INTEGER NOT NULL, "
                    "failures INTEGER NOT NULL, time_sum REAL NOT NULL, "
                    "time_sq REAL NOT NULL, damage_sum REAL NOT NULL, "
                    "last_seen REAL NOT NULL, features TEXT, "
                    "PRIMARY KEY (map_sha, scope, pace, from_key, to_key, mode))")
                self.db.execute(
                    "INSERT INTO edge_stats_v2(map_sha,scope,from_key,to_key,mode,attempts,"
                    "successes,failures,time_sum,time_sq,damage_sum,last_seen,features) "
                    "SELECT map_sha,scope,from_key,to_key,mode,attempts,successes,"
                    "failures,time_sum,time_sq,damage_sum,last_seen,features FROM edge_stats")
                self.db.execute("DROP TABLE edge_stats")
                self.db.execute("ALTER TABLE edge_stats_v2 RENAME TO edge_stats")

    # -- manifest ------------------------------------------------------
    def _save_manifest(self) -> None:
        temporary = self.manifest_path.with_name(self.manifest_path.name + ".tmp")
        temporary.write_text(json.dumps(self.manifest, indent=2, sort_keys=True) + "\n",
                             encoding="utf-8")
        temporary.replace(self.manifest_path)

    def close(self) -> None:
        self.db.close()

    # -- decision ledger -------------------------------------------------
    def append_decision(self, kind: str, features: dict, *, teacher=None,
                        selected=None, applied=None, candidates=None,
                        outcome=None, map_sha: str = "", scope: str = "",
                        policy_hash: str = "", pace: str = "unknown",
                        build: str = "") -> int:
        if not kind or not isinstance(features, dict):
            raise ValueError("A decision needs a kind and a features object.")
        for name, value in (("teacher", teacher), ("selected", selected),
                            ("applied", applied)):
            if value is not None and value not in (0, 1):
                raise ValueError(f"Decision {name} must be 0, 1 or None.")
        with self.db:
            cursor = self.db.execute(
                "INSERT INTO decisions(ts,kind,map_sha,scope,policy_hash,pace,build,features,"
                "candidates,teacher,selected,applied,outcome) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (time.time(), kind, map_sha, scope, policy_hash, pace, build, _packed(features),
                 _packed(candidates) if candidates is not None else None,
                 teacher, selected, applied,
                 _packed(outcome) if outcome is not None else None))
        return int(cursor.lastrowid)

    def decisions(self, kind: str | None = None, limit: int = 100000) -> list[dict]:
        query = ("SELECT kind,map_sha,scope,policy_hash,pace,build,features,candidates,"
                 "teacher,selected,applied,outcome FROM decisions")
        rows = self.db.execute(
            query + (" WHERE kind=? ORDER BY id LIMIT ?" if kind else " ORDER BY id LIMIT ?"),
            ((kind, limit) if kind else (limit,)))
        out = []
        for kind_, map_sha, scope, policy, pace, build, features, candidates, teacher, selected, applied, outcome in rows:
            out.append({"kind": kind_, "map_sha": map_sha, "scope": scope,
                        "policy_hash": policy, "pace": pace, "build": build,
                        "features": json.loads(features),
                        "candidates": json.loads(candidates) if candidates else None,
                        "teacher": teacher, "selected": selected, "applied": applied,
                        "outcome": json.loads(outcome) if outcome else None})
        return out

    # -- map edge statistics ----------------------------------------------
    def record_edge(self, map_sha: str, scope: str, from_key: str, to_key: str,
                    mode: int, success: bool, *, seconds: float | None = None,
                    damage: float = 0.0, features: dict | None = None,
                    attempts: int = 1, pace: str = "unknown") -> None:
        if type(mode) is not int or type(success) is not bool or attempts < 1:
            raise ValueError("Edge outcome needs an int mode, bool success, attempts >= 1.")
        seconds = 0.0 if seconds is None else _finite_number(seconds, "edge seconds")
        damage = _finite_number(damage, "edge damage")
        if seconds < 0 or damage < 0:
            raise ValueError("Edge seconds and damage cannot be negative.")
        wins = attempts if success else 0
        with self.db:
            self.db.execute(
                "INSERT INTO edge_stats VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(map_sha,scope,pace,from_key,to_key,mode) DO UPDATE SET "
                "attempts=attempts+excluded.attempts, successes=successes+excluded.successes, "
                "failures=failures+excluded.failures, time_sum=time_sum+excluded.time_sum, "
                "time_sq=time_sq+excluded.time_sq, damage_sum=damage_sum+excluded.damage_sum, "
                "last_seen=excluded.last_seen, "
                "features=COALESCE(excluded.features, features)",
                (map_sha, scope, pace, from_key, to_key, mode, attempts, wins,
                 attempts - wins, seconds * attempts, seconds * seconds * attempts,
                 damage * attempts, time.time(),
                 _packed(features) if features is not None else None))

    def edge_estimate(self, map_sha: str, scope: str, from_key: str, to_key: str,
                      mode: int, pace: str = "unknown") -> dict:
        row = self.db.execute(
            "SELECT attempts,successes,failures,time_sum,damage_sum FROM edge_stats "
            "WHERE map_sha=? AND scope=? AND pace=? AND from_key=? AND to_key=? AND mode=?",
            (map_sha, scope, pace, from_key, to_key, mode)).fetchone()
        if not row:
            return {"attempts": 0, "successes": 0, "failures": 0,
                    "probability": 0.5, "mean_seconds": None, "mean_damage": 0.0}
        attempts, successes, failures, time_sum, damage_sum = row
        return {"attempts": attempts, "successes": successes, "failures": failures,
                "probability": (successes + 1) / (attempts + 2),
                "mean_seconds": time_sum / attempts if attempts else None,
                "mean_damage": damage_sum / attempts if attempts else 0.0}

    def edge_rows(self) -> list[dict]:
        rows = self.db.execute(
            "SELECT map_sha,scope,pace,from_key,to_key,mode,attempts,successes,"
            "failures,features FROM edge_stats ORDER BY map_sha,scope,pace,from_key,to_key,mode")
        return [{"map_sha": m, "scope": s, "pace": p, "from_key": f, "to_key": t, "mode": mode,
                 "attempts": a, "successes": ok, "failures": bad,
                 "features": json.loads(features) if features else None}
                for m, s, p, f, t, mode, a, ok, bad, features in rows]

    def ingest_nav_log(self, text: str, map_sha: str, scope: str,
                       pace: str = "unknown") -> int:
        count = 0
        for event, from_key, to_key, mode in _NAV_LEARN.findall(text):
            self.record_edge(map_sha, scope, from_key.lower(), to_key.lower(),
                             int(mode), event == "arrive", pace=pace)
            count += 1
        return count

    def ingest_edge_log(self, text: str, map_sha: str, scope: str,
                        pace: str = "unknown") -> int:
        """Import BOT_EDGE_ATTEMPT telemetry with trainable geometry features."""
        count = 0
        for (event, from_key, to_key, mode, dist_mm, dz_mm, from_water,
             to_water, dest_item, base_milli, degree_from, degree_to) in \
                _EDGE_ATTEMPT.findall(text):
            features = {"distance": int(dist_mm) / 1000.0, "dz": int(dz_mm) / 1000.0,
                        "mode": int(mode), "from_water": int(from_water),
                        "to_water": int(to_water), "dest_item": int(dest_item),
                        "base_cost": int(base_milli) / 1000.0,
                        "degree_from": int(degree_from), "degree_to": int(degree_to)}
            self.record_edge(map_sha, scope, from_key.lower(), to_key.lower(),
                             int(mode), event == "arrive", features=features, pace=pace)
            count += 1
        return count

    def ingest_nav_file(self, path: Path, map_sha: str, scope: str,
                        pace: str = "unknown") -> int:
        """Import a v1 .nav recall file as lower-bound failure evidence."""
        count = 0
        for line in Path(path).read_text(encoding="ascii").splitlines():
            fields = line.split()
            if len(fields) != 5:
                continue
            try:
                mode, level = int(fields[2]), int(fields[3])
            except ValueError:
                continue
            if level < 1:
                continue
            self.record_edge(map_sha, scope, fields[0].lower(), fields[1].lower(),
                             mode, False, attempts=level, pace=pace)
            count += 1
        return count

    # -- coach bandit statistics -------------------------------------------
    def import_coach_memory(self, stored: dict) -> int:
        """Import bots.coach memory (PR4 and PR3 formats) as snapshots.

        Re-importing replaces the stored plays/total per label+build+arm,
        mirroring save_memory's whole-record write. Returns arm rows.
        """
        if not isinstance(stored, dict):
            raise ValueError("Coach memory must be a JSON object.")
        count = 0
        with self.db:
            for label, row in stored.items():
                if not isinstance(row, dict):
                    continue
                if isinstance(row.get("arms"), dict):
                    build = row.get("build") if isinstance(row.get("build"), str) else "unrecorded"
                    arms = row["arms"]
                else:
                    build, arms = "unrecorded", row
                for arm, stats in arms.items():
                    if not isinstance(stats, dict):
                        continue
                    plays, total = stats.get("plays"), stats.get("total")
                    if type(plays) is not int or plays < 0 or \
                            type(total) not in (int, float) or not math.isfinite(total):
                        continue
                    self.db.execute(
                        "INSERT INTO coach_arms VALUES(?,?,?,?,?) "
                        "ON CONFLICT(label,build,arm) DO UPDATE SET "
                        "plays=excluded.plays, total=excluded.total",
                        (label, build, arm, plays, float(total)))
                    count += 1
        return count

    def export_coach_memory(self) -> dict:
        """Export in the bots.coach PR4 file shape (extra builds @-suffixed)."""
        rows = self.db.execute(
            "SELECT label,build,arm,plays,total FROM coach_arms "
            "ORDER BY label,build,arm")
        by_label: dict[str, dict[str, dict]] = {}
        for label, build, arm, plays, total in rows:
            by_label.setdefault(label, {}).setdefault(build, {})[arm] = {
                "plays": plays, "total": total}
        out = {}
        for label, builds in by_label.items():
            ordered = sorted(builds)
            primary = ordered[0]
            out[label] = {"build": primary, "arms": builds[primary]}
            for extra in ordered[1:]:
                out[f"{label}@{extra}"] = {"build": extra, "arms": builds[extra]}
        return out

    def record_coach(self, label: str, build: str, arm: str, reward: float) -> None:
        reward = _finite_number(reward, "coach reward")
        with self.db:
            self.db.execute(
                "INSERT INTO coach_arms VALUES(?,?,?,?,?) "
                "ON CONFLICT(label,build,arm) DO UPDATE SET "
                "plays=plays+1, total=total+excluded.total",
                (label, build or "unrecorded", arm, 1, reward))

    def coach_arms(self, label: str, build: str | None = None) -> dict:
        query = "SELECT arm,plays,total FROM coach_arms WHERE label=?"
        args: tuple = (label,)
        if build is not None:
            query += " AND build=?"
            args = (label, build)
        return {arm: {"plays": plays, "total": total}
                for arm, plays, total in self.db.execute(query + " ORDER BY arm", args)}

    # -- model registry ----------------------------------------------------
    def register_model(self, path: Path, kind: str, scope: str,
                       metrics: dict | None = None) -> str:
        raw = Path(path).read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        target = self.root / "models" / f"{digest}.bin"
        if not target.exists():
            target.write_bytes(raw)
        if not any(m["sha256"] == digest for m in self.manifest["models"]):
            self.manifest["models"].append(
                {"sha256": digest, "kind": kind, "scope": scope,
                 "file": f"models/{digest}.bin", "metrics": metrics or {},
                 "status": "candidate", "registered_at": time.time()})
            self._save_manifest()
        return digest

    def _model(self, digest: str) -> dict:
        for model in self.manifest["models"]:
            if model["sha256"] == digest:
                return model
        raise ValueError(f"Unknown model: {digest}")

    def promote_model(self, digest: str, *, safety_ok: bool, heldout_ok: bool) -> None:
        if not (safety_ok and heldout_ok):
            raise ValueError("Promotion requires safety and held-out gates.")
        model = self._model(digest)
        key = f"{model['kind']}|{model['scope']}"
        previous = self.manifest["active"].get(key)
        if previous and previous != digest:
            self._model(previous)["status"] = "superseded"
        model["status"] = "active"
        model["promoted_at"] = time.time()
        self.manifest["active"][key] = digest
        self.manifest["history"].append(
            {"key": key, "sha256": digest, "action": "promote", "at": time.time()})
        self._save_manifest()

    def rollback(self, kind: str, scope: str) -> str:
        key = f"{kind}|{scope}"
        current = self.manifest["active"].get(key)
        superseded = [m for m in self.manifest["models"]
                      if m["kind"] == kind and m["scope"] == scope
                      and m["status"] == "superseded"]
        if not current or not superseded:
            raise ValueError("No superseded model to roll back to.")
        target = max(superseded, key=lambda m: m.get("promoted_at", 0))
        self._model(current)["status"] = "superseded"
        target["status"] = "active"
        self.manifest["active"][key] = target["sha256"]
        self.manifest["history"].append(
            {"key": key, "sha256": target["sha256"], "action": "rollback",
             "at": time.time()})
        self._save_manifest()
        return target["sha256"]

    def active_model(self, kind: str, scope: str) -> dict | None:
        digest = self.manifest["active"].get(f"{kind}|{scope}")
        return self._model(digest) if digest else None


DUEL_FEATURES = ("health", "shields", "enemy_mm", "item_mm", "weapon", "ammo",
                 "pack", "wet", "remaining_route_nodes")
_DUEL = re.compile(
    r"BOT_DUEL .*f=(-?\d+(?:,-?\d+){8}) teacher=([01]) selected=([01]) "
    r"applied=([01]) owner=(\S+) model=(\S+)")


def ingest_duel_log(store: BrainStore, text: str, map_sha: str, scope: str,
                    pace: str = "unknown", build: str = "") -> int:
    """Import native BOT_DUEL pickup/engage decisions into the ledger."""
    count = 0
    for values, teacher, selected, applied, owner, model in _DUEL.findall(text):
        features = dict(zip(DUEL_FEATURES, (int(v) for v in values.split(","))))
        store.append_decision(
            "pickup_engage", features, teacher=int(teacher),
            selected=int(selected), applied=int(applied), candidates=[0, 1],
            outcome={"owner": owner}, map_sha=map_sha, scope=scope,
            policy_hash=model, pace=pace, build=build)
        count += 1
    return count


def leave_one_map_out(rows) -> dict:
    """Held-out-map report for aggregated edge rows carrying map_sha.

    Each entry trains on every other map and scores only the held-out
    map, so map memorization cannot inflate the number. Rows are
    BrainStore.edge_rows() dicts (features may be None; those are
    skipped and counted under ``skipped_no_features`` per map).
    """
    by_map: dict[str, list] = {}
    skipped: dict[str, int] = {}
    for row in rows:
        if not row.get("features"):
            skipped[row["map_sha"]] = skipped.get(row["map_sha"], 0) + 1
            continue
        by_map.setdefault(row["map_sha"], []).append(
            (row["features"], row["successes"], row["failures"]))
    if len(by_map) < 2:
        raise ValueError("Leave-one-map-out needs featured rows from two maps.")
    report = {}
    for held in sorted(by_map):
        train = [entry for other, entries in by_map.items() if other != held
                 for entry in entries]
        model = fit_edge_model(train)
        correct = {0.0: 0, 1.0: 0}
        totals = {0.0: 0, 1.0: 0}
        for features, successes, failures in by_map[held]:
            predicted = 1.0 if predict_edge(model, features) >= 0.5 else 0.0
            totals[1.0] += successes
            totals[0.0] += failures
            if predicted == 1.0:
                correct[1.0] += successes
            else:
                correct[0.0] += failures
        recalls = [correct[label] / totals[label] if totals[label] else 0.0
                   for label in (0.0, 1.0)]
        report[held] = {"train_maps": len(by_map) - 1,
                        "attempts": int(totals[0.0] + totals[1.0]),
                        "balanced_accuracy": sum(recalls) / 2,
                        "skipped_no_features": skipped.get(held, 0)}
    return report


# -- global edge model (offline NumPy training, plain-JSON artifact) -------

def _feature_vector(features: dict) -> list[float]:
    if not isinstance(features, dict):
        raise ValueError("Edge features must be an object.")
    unknown = set(features) - set(EDGE_FEATURES)
    if unknown:
        raise ValueError(f"Unknown edge features: {sorted(unknown)}")
    vector = [_finite_number(features.get(name, 0.0), f"edge feature {name}")
              for name in EDGE_FEATURES]
    vector[EDGE_FEATURES.index("abs_dz")] = abs(vector[EDGE_FEATURES.index("dz")]) \
        if "abs_dz" not in features else vector[EDGE_FEATURES.index("abs_dz")]
    return vector


def fit_edge_model(rows, *, steps: int = 400, learning_rate: float = 0.2,
                   l2: float = 1e-4) -> dict:
    """Fit weighted logistic regression over (features, successes, failures).

    Deterministic zero initialization; the objective is convex, so no seed
    is needed. Rows may come from BrainStore.edge_rows() aggregates.
    """
    try:
        import numpy as np
    except ImportError as exc:
        raise ValueError("Offline edge training needs NumPy; inference does not.") from exc
    rows = list(rows)
    if not rows:
        raise ValueError("No edge rows to fit.")
    x_rows, weights, labels = [], [], []
    for features, successes, failures in rows:
        vector = _feature_vector(features)
        for count, label in ((successes, 1.0), (failures, 0.0)):
            if type(count) is not int or count < 0:
                raise ValueError("Edge success/failure counts must be non-negative ints.")
            if count:
                x_rows.append(vector)
                weights.append(float(count))
                labels.append(label)
    if not x_rows or len(set(labels)) < 2:
        raise ValueError("Edge training needs both successes and failures.")
    fitted = _fit_logistic(x_rows, labels, weights,
                            steps=steps, learning_rate=learning_rate, l2=l2)
    fitted["train"] = {"rows": len(rows), "attempts": fitted["train"]["attempts"],
                       "accuracy": fitted["train"]["accuracy"],
                       "balanced_accuracy": fitted["train"]["balanced_accuracy"]}
    fitted["features"] = list(EDGE_FEATURES)
    return fitted


def _fit_logistic_torch(x_rows, labels, weights, *, steps, learning_rate, l2, device):
    """Torch twin of the NumPy fit below: same standardization, zero init,
    full-batch steps and clipping, in float64 so artifacts agree closely.

    Selected with BRAIN_FIT_BACKEND=torch[:cpu|cuda]. Worthwhile only once
    ledgers reach ~1e6 rows; the NumPy path stays the default.
    """
    import torch
    if device is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"
    x = torch.tensor(x_rows, dtype=torch.float64, device=device)
    y = torch.tensor(labels, dtype=torch.float64, device=device)
    w = torch.tensor(weights, dtype=torch.float64, device=device)
    total = w.sum()
    centers = (x * w.unsqueeze(1)).sum(0) / total
    scales = torch.sqrt(((x - centers) ** 2 * w.unsqueeze(1)).sum(0) / total)
    scales = torch.where(scales > 1e-9, scales, torch.ones_like(scales))
    z = (x - centers) / scales
    coef = torch.zeros(z.shape[1], dtype=torch.float64, device=device)
    bias = torch.zeros((), dtype=torch.float64, device=device)
    for _ in range(steps):
        p = torch.sigmoid(torch.clamp(z @ coef + bias, -30, 30))
        err = w * (p - y)
        coef -= learning_rate * ((z.T @ err) / total + l2 * coef)
        bias -= learning_rate * (err.sum() / total)
    p = torch.sigmoid(torch.clamp(z @ coef + bias, -30, 30))
    pred = (p >= 0.5).to(torch.float64)
    accuracy = float(((pred == y).to(torch.float64) * w).sum() / total)
    recalls = []
    for label in (0.0, 1.0):
        mask = y == label
        recalls.append(float(((pred[mask] == y[mask]).to(torch.float64) * w[mask]).sum() / w[mask].sum())
                       if bool(mask.any()) else 0.0)
    return {"schema": 1, "features": [],
            "centers": [float(v) for v in centers.cpu()],
            "scales": [float(v) for v in scales.cpu()],
            "weights": [float(v) for v in coef.cpu()], "bias": float(bias.cpu()),
            "train": {"attempts": int(total.cpu()), "accuracy": accuracy,
                      "balanced_accuracy": sum(recalls) / 2}}


def _fit_logistic(x_rows, labels, weights, *, steps, learning_rate, l2):
    """Shared deterministic weighted logistic fit (convex, zero init)."""
    backend = os.environ.get("BRAIN_FIT_BACKEND", "numpy")
    if backend.startswith("torch"):
        device = backend.partition(":")[2] or None
        return _fit_logistic_torch(x_rows, labels, weights, steps=steps,
                                    learning_rate=learning_rate, l2=l2,
                                    device=device)
    if backend != "numpy":
        raise ValueError(f"Unknown BRAIN_FIT_BACKEND {backend!r} (numpy|torch[:cpu|cuda]).")
    import numpy as np
    x = np.asarray(x_rows, dtype=float)
    y = np.asarray(labels, dtype=float)
    w = np.asarray(weights, dtype=float)
    centers = np.average(x, axis=0, weights=w)
    scales = np.sqrt(np.average((x - centers) ** 2, axis=0, weights=w))
    scales = np.where(scales > 1e-9, scales, 1.0)
    z = (x - centers) / scales
    coef = np.zeros(z.shape[1])
    bias = 0.0
    total = w.sum()
    for _ in range(steps):
        p = 1.0 / (1.0 + np.exp(-np.clip(z @ coef + bias, -30, 30)))
        err = w * (p - y)
        coef -= learning_rate * ((z.T @ err) / total + l2 * coef)
        bias -= learning_rate * float(err.sum() / total)
    p = 1.0 / (1.0 + np.exp(-np.clip(z @ coef + bias, -30, 30)))
    pred = (p >= 0.5).astype(float)
    accuracy = float(np.average(pred == y, weights=w))
    recalls = []
    for label in (0.0, 1.0):
        mask = y == label
        recalls.append(float(np.average(pred[mask] == y[mask], weights=w[mask]))
                       if mask.any() else 0.0)
    return {"schema": 1, "features": [],
            "centers": [float(v) for v in centers],
            "scales": [float(v) for v in scales],
            "weights": [float(v) for v in coef], "bias": float(bias),
            "train": {"attempts": int(total), "accuracy": accuracy,
                      "balanced_accuracy": sum(recalls) / 2}}


def _predict_logistic(model, vector) -> float:
    score = float(model["bias"])
    for value, center, scale, weight in zip(
            vector, model["centers"], model["scales"], model["weights"]):
        score += weight * (value - center) / scale
    return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, score))))


def _validate_edge_model(model) -> dict:
    if (not isinstance(model, dict) or model.get("schema") != 1
            or tuple(model.get("features", ())) != EDGE_FEATURES):
        raise ValueError("Expected edge-model schema 1 with the canonical features.")
    for key in ("centers", "scales", "weights"):
        values = model.get(key)
        if (not isinstance(values, list) or len(values) != len(EDGE_FEATURES)
                or any(type(v) is bool or not isinstance(v, (int, float))
                       or not math.isfinite(v) for v in values)):
            raise ValueError(f"Malformed edge-model {key}.")
    if any(v <= 0 for v in model["scales"]):
        raise ValueError("Edge-model scales must be positive.")
    _finite_number(model.get("bias"), "edge-model bias")
    return model


def predict_edge(model: dict, features: dict) -> float:
    _validate_edge_model(model)
    vector = _feature_vector(features)
    score = float(model["bias"])
    for value, center, scale, weight in zip(
            vector, model["centers"], model["scales"], model["weights"]):
        score += weight * (value - center) / scale
    return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, score))))


def save_edge_model(model: dict, path: Path) -> str:
    _validate_edge_model(model)
    raw = (json.dumps(model, sort_keys=True, separators=(",", ":"),
                      allow_nan=False) + "\n").encode("utf-8")
    Path(path).write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def export_edge_native(model: dict, path: Path) -> str:
    """Write the ADJOIN_EDGE_V1 text form consumed by red_transfer.inc."""
    _validate_edge_model(model)
    lines = [f"ADJOIN_EDGE_V1 {len(EDGE_FEATURES)}"]
    for key in ("centers", "scales", "weights"):
        lines.append(" ".join(f"{float(v):.9g}" for v in model[key]))
    lines.append(f"{float(model['bias']):.9g}")
    raw = ("\n".join(lines) + "\n").encode("ascii")
    Path(path).write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def parse_edge_native(text: str) -> dict:
    """Parse ADJOIN_EDGE_V1 text (test/parity helper mirroring the C loader)."""
    tokens = text.split()
    if len(tokens) != 2 + 3 * len(EDGE_FEATURES) + 1 or tokens[0] != "ADJOIN_EDGE_V1":
        raise ValueError("Malformed ADJOIN_EDGE_V1 text.")
    count = int(tokens[1])
    if count != len(EDGE_FEATURES):
        raise ValueError("ADJOIN_EDGE_V1 feature count mismatch.")
    numbers = [float(v) for v in tokens[2:]]
    if not all(math.isfinite(v) for v in numbers):
        raise ValueError("ADJOIN_EDGE_V1 values must be finite.")
    n = len(EDGE_FEATURES)
    return _validate_edge_model({
        "schema": 1, "features": list(EDGE_FEATURES),
        "centers": numbers[0:n], "scales": numbers[n:2 * n],
        "weights": numbers[2 * n:3 * n], "bias": numbers[3 * n]})


def load_edge_model(path: Path, expected_sha256: str | None = None) -> dict:
    raw = Path(path).read_bytes()
    if expected_sha256 is not None and hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError("Edge-model hash mismatch.")
    return _validate_edge_model(json.loads(raw.decode("utf-8")))


# -- generic decision distillation -----------------------------------------

def _decision_vector(features: dict, names) -> list[float]:
    if not isinstance(features, dict):
        raise ValueError("Decision features must be an object.")
    return [_finite_number(features.get(name, 0.0), f"decision feature {name}")
            for name in names]


def fit_decision_model(rows, feature_names, *, steps: int = 400,
                       learning_rate: float = 0.2, l2: float = 1e-4) -> dict:
    """Distill binary teacher labels over caller-chosen decision features.

    Rows are (features, label) pairs or BrainStore decision dicts whose
    ``teacher`` field is the label. This is imitation only; outcome
    improvement still needs live candidate matches and promotion gates.
    """
    names = tuple(feature_names)
    if not names or len(set(names)) != len(names):
        raise ValueError("Decision feature names must be non-empty and unique.")
    x_rows, labels = [], []
    for row in rows:
        if isinstance(row, dict) and "features" in row:
            label = row.get("teacher")
            if label is None:
                continue
            features = row["features"]
        else:
            features, label = row
        if label not in (0, 1):
            raise ValueError("Decision labels must be 0 or 1.")
        x_rows.append(_decision_vector(features, names))
        labels.append(float(label))
    if len(set(labels)) < 2:
        raise ValueError("Decision training needs both labels.")
    model = _fit_logistic(x_rows, labels, [1.0] * len(labels),
                           steps=steps, learning_rate=learning_rate, l2=l2)
    model["kind"] = "decision"
    model["features"] = list(names)
    model["train"] = {"rows": len(labels), **model["train"]}
    return model


def _validate_decision_model(model) -> dict:
    if (not isinstance(model, dict) or model.get("schema") != 1
            or model.get("kind") != "decision"
            or not isinstance(model.get("features"), list) or not model["features"]):
        raise ValueError("Expected decision-model schema 1.")
    n = len(model["features"])
    for key in ("centers", "scales", "weights"):
        values = model.get(key)
        if (not isinstance(values, list) or len(values) != n
                or any(type(v) is bool or not isinstance(v, (int, float))
                       or not math.isfinite(v) for v in values)):
            raise ValueError(f"Malformed decision-model {key}.")
    if any(v <= 0 for v in model["scales"]):
        raise ValueError("Decision-model scales must be positive.")
    _finite_number(model.get("bias"), "decision-model bias")
    return model


def predict_decision(model: dict, features: dict) -> float:
    _validate_decision_model(model)
    return _predict_logistic(model, _decision_vector(features, model["features"]))


def save_decision_model(model: dict, path: Path) -> str:
    _validate_decision_model(model)
    raw = (json.dumps(model, sort_keys=True, separators=(",", ":"),
                      allow_nan=False) + "\n").encode("utf-8")
    Path(path).write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def load_decision_model(path: Path, expected_sha256: str | None = None) -> dict:
    raw = Path(path).read_bytes()
    if expected_sha256 is not None and hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError("Decision-model hash mismatch.")
    return _validate_decision_model(json.loads(raw.decode("utf-8")))


RED_HIDDEN = 8
RED_Q = 1024


def export_red_neural(model: dict, path: Path) -> str:
    """Export a Brain logistic decision model as native RED_NEURAL_V1.

    The native pickup network standardizes inputs with integer
    centers/scales, so the logistic head embeds exactly (up to integer
    quantization) as two hidden units: relu(z) - relu(-z) == z, with the
    remaining units zero. Feature order must be DUEL_FEATURES, the order
    the native BOT_DUEL telemetry and Red policy both use.
    """
    _validate_decision_model(model)
    if tuple(model["features"]) != DUEL_FEATURES:
        raise ValueError("RED_NEURAL_V1 export requires DUEL_FEATURES order.")
    centers = [int(round(v)) for v in model["centers"]]
    scales = [max(1, int(round(v))) for v in model["scales"]]
    weights = [float(v) for v in model["weights"]]
    bias = float(model["bias"])
    limits = [16384 / abs(w) for w in weights if w]
    if bias:
        limits.append(33554432 / (abs(bias) * RED_Q))
    gain = int(min(limits)) if limits else 1024
    if gain < 1:
        raise ValueError("Decision weights too large for RED_NEURAL_V1 ranges.")
    w_row = [int(round(w * gain)) for w in weights]
    b_row = int(round(bias * gain * RED_Q))
    hidden = [[b_row, *w_row], [-b_row, *[-w for w in w_row]]]
    hidden += [[0] * (len(DUEL_FEATURES) + 1) for _ in range(RED_HIDDEN - 2)]
    output = [0, 1, -1] + [0] * (RED_HIDDEN - 2)
    lines = [f"RED_NEURAL_V1 {len(DUEL_FEATURES)} {RED_HIDDEN}",
             " ".join(map(str, centers)), " ".join(map(str, scales))]
    lines += [" ".join(map(str, row)) for row in hidden]
    lines.append(" ".join(map(str, output)))
    raw = ("\n".join(lines) + "\n").encode("ascii")
    Path(path).write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def predict_red_neural(text: str, features: dict) -> int:
    """Integer mirror of native Red_Score >= 0 for parity checks."""
    lines = text.splitlines()
    if not lines or lines[0] != f"RED_NEURAL_V1 {len(DUEL_FEATURES)} {RED_HIDDEN}":
        raise ValueError("Malformed RED_NEURAL_V1 header.")
    rows = [tuple(map(int, row.split())) for row in lines[1:]]
    if len(rows) != RED_HIDDEN + 3:
        raise ValueError("Malformed RED_NEURAL_V1 dimensions.")
    centers, scales, hidden, output = rows[0], rows[1], rows[2:-1], rows[-1]
    values = _decision_vector(features, DUEL_FEATURES)
    z = []
    for value, center, scale in zip(values, centers, scales):
        scaled = int((int(value) - center) * RED_Q / scale)
        z.append(max(-2 * RED_Q, min(2 * RED_Q, scaled)))
    score = output[0]
    for (hidden_bias, *hidden_weights), out_weight in zip(hidden, output[1:]):
        acc = hidden_bias + sum(w * v for w, v in zip(hidden_weights, z))
        unit = max(0, min(32 * RED_Q, int(acc / RED_Q)))
        score += out_weight * unit
    return int(score >= 0)


def train_decision_from_store(store: BrainStore, kind: str, feature_names) -> dict:
    """Fit a distillation head from ledger rows of one decision kind."""
    return fit_decision_model(store.decisions(kind), feature_names)


# Outcome training: move past imitation by weighting taken actions with
# their observed advantage. Rewards are deliberately simple and auditable;
# unrecognized outcome keys never contribute.
REWARD_WEIGHTS = {
    "kill": 3.0, "death": -3.0, "capture": 5.0, "pickup": 1.0,
    "damage_dealt": 0.02, "damage_taken": -0.02,
    "route_success": 1.0, "route_failure": -1.0,
}


def reward_from_outcome(outcome) -> float | None:
    """Scalar reward from recognized numeric outcome fields, else None."""
    if not isinstance(outcome, dict):
        return None
    total = 0.0
    seen = False
    for key, weight in REWARD_WEIGHTS.items():
        if key not in outcome:
            continue
        value = outcome[key]
        if type(value) is bool:
            value = float(value)
        total += weight * _finite_number(value, f"outcome {key}")
        seen = True
    return total if seen else None


def _taken_label(row: dict):
    for field in ("applied", "selected", "teacher"):
        if row.get(field) is not None:
            return row[field]
    return None


def fit_outcome_model(rows, feature_names, *, temperature: float = 1.0,
                      max_weight: float = 10.0, steps: int = 400,
                      learning_rate: float = 0.2, l2: float = 1e-4) -> dict:
    """Advantage-weighted regression over ledger rows with outcomes.

    Each rewarded row contributes its taken action (applied, else
    selected, else teacher) weighted by exp(advantage / temperature),
    where advantage is reward minus the mean reward of the same action.
    Actions that worked in a context count more; actions that failed
    count less but are never deleted. This is offline improvement over
    the teacher distribution, not on-policy reinforcement learning.
    """
    if temperature <= 0 or max_weight < 1:
        raise ValueError("Outcome temperature must be > 0 and max_weight >= 1.")
    names = tuple(feature_names)
    if not names or len(set(names)) != len(names):
        raise ValueError("Decision feature names must be non-empty and unique.")
    samples = []
    for row in rows:
        label = _taken_label(row)
        reward = reward_from_outcome(row.get("outcome"))
        if label is None or reward is None:
            continue
        if label not in (0, 1):
            raise ValueError("Outcome labels must be 0 or 1.")
        samples.append((_decision_vector(row["features"], names), float(label), reward))
    labels = {label for _vector, label, _reward in samples}
    if len(labels) < 2:
        raise ValueError("Outcome training needs rewarded rows for both actions.")
    means = {}
    for label in (0.0, 1.0):
        rewards = [reward for _v, taken, reward in samples if taken == label]
        means[label] = sum(rewards) / len(rewards)
    x_rows = [vector for vector, _label, _reward in samples]
    y = [label for _vector, label, _reward in samples]
    weights = [min(max_weight, max(0.05, math.exp((reward - means[label]) / temperature)))
               for _vector, label, reward in samples]
    model = _fit_logistic(x_rows, y, weights, steps=steps,
                           learning_rate=learning_rate, l2=l2)
    model["kind"] = "decision"
    model["features"] = list(names)
    model["train"] = {"rows": len(samples), "outcome_weighted": True,
                      "temperature": temperature,
                      "reward_mean": sum(r for _v, _l, r in samples) / len(samples),
                      **model["train"]}
    return model


def train_outcome_from_store(store: BrainStore, kind: str, feature_names,
                             **kwargs) -> dict:
    """Fit an outcome-weighted head from ledger rows of one decision kind."""
    return fit_outcome_model(store.decisions(kind), feature_names, **kwargs)


def evaluate_decision_candidate(rows, model) -> dict:
    """Shadow metrics for a decision candidate over labelled ledger rows.

    Reward comparisons use only rows whose taken action agrees with the
    candidate (observed reward) versus rows where it disagrees (reward of
    the other taken action). That is evidence about where the candidate
    would have matched good outcomes, not a counterfactual guarantee.
    """
    _validate_decision_model(model)
    labelled = correct = rewarded = agreed = 0
    per_class = {0: [0, 0], 1: [0, 0]}
    agreed_reward = disagreed_reward = 0.0
    agreed_rewarded = disagreed_rewarded = 0
    maps = set()
    for row in rows:
        label = _taken_label(row)
        if label is None:
            continue
        labelled += 1
        maps.add(row.get("map_sha", ""))
        predicted = 1 if predict_decision(model, row["features"]) >= 0.5 else 0
        per_class[label][1] += 1
        if predicted == label:
            correct += 1
            per_class[label][0] += 1
            agreed += 1
        reward = reward_from_outcome(row.get("outcome"))
        if reward is not None:
            rewarded += 1
            if predicted == label:
                agreed_reward += reward
                agreed_rewarded += 1
            else:
                disagreed_reward += reward
                disagreed_rewarded += 1
    recalls = [per_class[k][0] / per_class[k][1] if per_class[k][1] else 0.0
               for k in (0, 1)]
    return {"rows": labelled, "maps": len(maps),
            "agreement": correct / labelled if labelled else 0.0,
            "balanced_accuracy": sum(recalls) / 2,
            "rewarded_rows": rewarded,
            "agreed_rows": agreed,
            "agreed_reward_mean": agreed_reward / agreed_rewarded if agreed_rewarded else None,
            "disagreed_reward_mean": disagreed_reward / disagreed_rewarded if disagreed_rewarded else None}


def qualify_decision_candidate(store: BrainStore, kind: str, model, *,
                               min_rows: int = 50,
                               min_balanced_accuracy: float = 0.7,
                               min_rewarded: int = 10,
                               require_maps: int = 2,
                               holdout_maps=None) -> dict:
    """Shadow-qualification gates for promoting a decision candidate.

    Passing means the offline evidence is strong enough to consider a
    live trial; promote_model still requires explicit safety and
    held-out confirmations from the operator.
    """
    rows = store.decisions(kind)
    if holdout_maps:
        wanted = set(holdout_maps)
        rows = [row for row in rows if row.get("map_sha", "") in wanted]
    metrics = evaluate_decision_candidate(rows, model)
    reasons = []
    if metrics["rows"] < min_rows:
        reasons.append(f"only {metrics['rows']} labelled rows (< {min_rows})")
    if metrics["maps"] < require_maps:
        reasons.append(f"only {metrics['maps']} map(s) represented (< {require_maps})")
    if metrics["balanced_accuracy"] < min_balanced_accuracy:
        reasons.append(
            f"balanced accuracy {metrics['balanced_accuracy']:.3f} < {min_balanced_accuracy}")
    if metrics["rewarded_rows"] < min_rewarded:
        reasons.append(f"only {metrics['rewarded_rows']} rewarded rows (< {min_rewarded})")
    elif (metrics["agreed_reward_mean"] is not None
          and metrics["disagreed_reward_mean"] is not None
          and metrics["agreed_reward_mean"] < metrics["disagreed_reward_mean"]):
        reasons.append("candidate agrees with worse observed outcomes than it rejects")
    return {"ok": not reasons, "reasons": reasons, "metrics": metrics}


_GEAR_PLAN = re.compile(
    r"BOT_GEAR .*event=plan item=(\d+) guid=(\d+) signature=(\d+) "
    r"pack=([01]) anchor=(-?\d+) direct=([01])")
_SWITCH = re.compile(
    r"BOT_SWITCH .*from=(\d+) to=(\d+) dist=([0-9.]+) los=([01]) air=([01]) why=(\S+)")
_FORCE_INPUT = re.compile(
    r"BOT_FORCE_INPUT .*bin=(\d+) level=([0-9.]+) mana=([0-9.]+) hold=([0-9.]+)")


def ingest_decision_log(store: BrainStore, text: str, map_sha: str, scope: str,
                        pace: str = "unknown", build: str = "") -> dict:
    """Import existing native decision telemetry into the ledger.

    Covers BOT_GEAR plans (goal choice), BOT_SWITCH (weapon change, tactics
    builds) and BOT_FORCE_INPUT (Force cast requests). Choices that are not
    binary keep ``selected`` empty and record the choice in the outcome.
    Returns per-kind counts.
    """
    counts = {"goal_plan": 0, "weapon_switch": 0, "force_cast": 0}
    for item, guid, signature, pack, anchor, direct in _GEAR_PLAN.findall(text):
        store.append_decision(
            "goal_plan", {"item": int(item), "pack": int(pack),
                          "anchor": int(anchor), "direct": int(direct)},
            outcome={"choice_item": int(item), "guid": int(guid),
                     "signature": int(signature)},
            map_sha=map_sha, scope=scope, pace=pace, build=build)
        counts["goal_plan"] += 1
    for current, chosen, dist, los, air, why in _SWITCH.findall(text):
        store.append_decision(
            "weapon_switch", {"from_weapon": int(current), "dist": float(dist),
                              "los": int(los), "air": int(air)},
            outcome={"choice_weapon": int(chosen), "why": why},
            map_sha=map_sha, scope=scope, pace=pace, build=build)
        counts["weapon_switch"] += 1
    for bin_, level, mana, hold in _FORCE_INPUT.findall(text):
        store.append_decision(
            "force_cast", {"bin": int(bin_), "level": float(level),
                           "mana": float(mana), "hold": float(hold)},
            selected=1, outcome={"bin": int(bin_)},
            map_sha=map_sha, scope=scope, pace=pace, build=build)
        counts["force_cast"] += 1
    return counts


_BOT_DECISION = re.compile(r"BOT_DECISION .*kind=(goal|weapon|force) (.+)$", re.M)
_DECISION_FIELD = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)=(\S+)")


def ingest_bot_decision_log(store: BrainStore, text: str, map_sha: str, scope: str,
                            pace: str = "unknown", build: str = "") -> int:
    """Import regenerated-tactics BOT_DECISION goal/weapon/Force lines.

    Numeric fields become features; ``choice`` (and weapon ``why``) are kept
    in the outcome because goal/weapon choices are not binary labels.
    """
    count = 0
    for kind, rest in _BOT_DECISION.findall(text):
        fields = dict(_DECISION_FIELD.findall(rest))
        try:
            choice = int(fields.pop("choice"))
            features = {}
            for name, raw in fields.items():
                if name == "why":
                    continue
                try:
                    features[name] = int(raw)
                except ValueError:
                    features[name] = float(raw)
        except (KeyError, ValueError):
            continue
        outcome = {"choice": choice}
        if "why" in fields:
            outcome["why"] = fields["why"]
        store.append_decision(kind, features, outcome=outcome,
                              map_sha=map_sha, scope=scope, pace=pace, build=build)
        count += 1
    return count


_BOT_STATUS = re.compile(
    r"BOT_STATUS name=(\S+) t=([0-9.]+) .*health=([0-9.]+) .*kills=(\d+) deaths=(\d+)")
_BOT_RED_STATE = re.compile(
    r"BOT_RED_STATE name=(\S+) t=([0-9.]+) .*hp=([0-9.]+) shields=[0-9.]+ .*kills=(\d+) deaths=(\d+)")
_DECISION_TIME = re.compile(r"BOT_(?:DECISION|DUEL) name=(\S+) t=([0-9.]+)")


def _status_series(text: str) -> dict:
    """Chronological BOT_STATUS/BOT_RED_STATE samples per bot.

    Red policy clients emit BOT_RED_STATE far more frequently than the
    periodic BOT_STATUS summary; both map to (t, kills, deaths, health).
    """
    series: dict[str, list] = {}
    for line in text.splitlines():
        match = _BOT_RED_STATE.search(line) or _BOT_STATUS.search(line)
        if not match:
            continue
        name, t, health, kills, deaths = match.groups()
        series.setdefault(name, []).append(
            (float(t), int(kills), int(deaths), float(health)))
    for points in series.values():
        points.sort(key=lambda point: point[0])
    return series


def _outcome_at(series, name: str, when: float, window: float) -> dict:
    """Kill/death/damage deltas for one bot in (when, when+window]."""
    points = series.get(name) or []
    base = None
    future = None
    for point in points:
        if point[0] <= when:
            base = point
        if when < point[0] <= when + window:
            future = point
    if base is None or future is None:
        return {}
    outcome = {}
    if future[1] > base[1]:
        outcome["kill"] = future[1] - base[1]
    if future[2] > base[2]:
        outcome["death"] = future[2] - base[2]
    drop = base[3] - future[3]
    if drop > 0:
        outcome["damage_taken"] = drop
    return outcome


def ingest_match_log(store: BrainStore, text: str, map_sha: str, scope: str,
                     pace: str = "unknown", build: str = "",
                     window: float = 5.0) -> dict:
    """Ingest one match log with outcomes attributed from BOT_STATUS deltas.

    Decisions (BOT_DECISION and BOT_DUEL) gain kill/death/damage_taken
    outcomes from the same bot's status series inside the attribution
    window - an approximation: kills are credited to every decision in
    the window, which the outcome trainer's advantage baseline absorbs.
    Edge telemetry in the same log is ingested too. Returns counts.
    """
    if window <= 0:
        raise ValueError("Attribution window must be positive.")
    series = _status_series(text)
    counts = {"bot_decision": 0, "pickup_engage": 0, "edges": 0, "attributed": 0}
    # BOT_DECISION rows with attributed outcomes.
    for line in text.splitlines():
        head = _DECISION_TIME.search(line)
        if not head:
            continue
        name, when = head.group(1), float(head.group(2))
        outcome = _outcome_at(series, name, when, window)
        duel = _DUEL.search(line)
        if duel:
            values, teacher, selected, applied, owner, model = duel.groups()
            features = dict(zip(DUEL_FEATURES, (int(v) for v in values.split(","))))
            merged = {"owner": owner, **outcome}
            store.append_decision(
                "pickup_engage", features, teacher=int(teacher),
                selected=int(selected), applied=int(applied), candidates=[0, 1],
                outcome=merged, map_sha=map_sha, scope=scope,
                policy_hash=model, pace=pace, build=build)
            counts["pickup_engage"] += 1
            counts["attributed"] += bool(outcome)
            continue
        decision = _BOT_DECISION.search(line)
        if decision:
            kind, rest = decision.groups()
            fields = dict(_DECISION_FIELD.findall(rest))
            try:
                choice = int(fields.pop("choice"))
                features = {}
                for key, raw in fields.items():
                    if key == "why":
                        continue
                    try:
                        features[key] = int(raw)
                    except ValueError:
                        features[key] = float(raw)
            except (KeyError, ValueError):
                continue
            merged = {"choice": choice, **outcome}
            if "why" in fields:
                merged["why"] = fields["why"]
            store.append_decision(kind, features, outcome=merged,
                                  map_sha=map_sha, scope=scope, pace=pace, build=build)
            counts["bot_decision"] += 1
            counts["attributed"] += bool(outcome)
    counts["edges"] = (store.ingest_edge_log(text, map_sha, scope, pace=pace)
                       + store.ingest_nav_log(text, map_sha, scope, pace=pace))
    counts.update(ingest_decision_log(store, text, map_sha, scope,
                                      pace=pace, build=build))
    return counts


def leave_one_map_out_decisions(rows, feature_names) -> dict:
    """Per-map distillation report; each map is scored by a model that
    never trained on it. Rows are BrainStore decision dicts."""
    by_map: dict[str, list] = {}
    for row in rows:
        if row.get("teacher") is None:
            continue
        by_map.setdefault(row.get("map_sha", ""), []).append(row)
    if len(by_map) < 2:
        raise ValueError("Decision LOMO needs labelled rows from two maps.")
    report = {}
    for held in sorted(by_map):
        train = [row for other, entries in by_map.items() if other != held
                 for row in entries]
        model = fit_decision_model(train, feature_names)
        correct = {0: 0, 1: 0}
        totals = {0: 0, 1: 0}
        for row in by_map[held]:
            predicted = 1 if predict_decision(model, row["features"]) >= 0.5 else 0
            totals[row["teacher"]] += 1
            if predicted == row["teacher"]:
                correct[row["teacher"]] += 1
        recalls = [correct[k] / totals[k] if totals[k] else 0.0 for k in (0, 1)]
        report[held] = {"train_maps": len(by_map) - 1,
                        "attempts": int(totals[0] + totals[1]),
                        "balanced_accuracy": sum(recalls) / 2}
    return report


def suggest_tactics(trials, current: dict | None = None, *,
                    step_fraction: float = 0.1) -> dict:
    """Advisory next tactics values from (values, reward) trial history.

    Fits a ridge reward model over range-normalized knobs and takes one
    bounded gradient step from ``current`` (defaults when omitted).
    Returns only knobs that move. Nothing is sent to a bot; the coach or
    operator decides whether to apply the suggestion as a preset trial.
    """
    from .tactics import DEFAULTS, RANGES, NAMES
    try:
        import numpy as np
    except ImportError as exc:
        raise ValueError("Tactics suggestion needs NumPy.") from exc
    trials = list(trials)
    if len(trials) < 8:
        raise ValueError("Tactics suggestion needs at least eight trials.")
    widths = {name: RANGES[name][1] - RANGES[name][0] for name in NAMES}
    base = dict(DEFAULTS)
    base.update(current or {})
    unknown = set(base) - set(NAMES)
    if unknown:
        raise ValueError(f"Unknown tactics knobs: {sorted(unknown)}")
    x_rows, rewards = [], []
    for values, reward in trials:
        unknown = set(values) - set(NAMES)
        if unknown:
            raise ValueError(f"Unknown tactics knobs: {sorted(unknown)}")
        merged = dict(DEFAULTS)
        merged.update(values)
        x_rows.append([(float(merged[name]) - RANGES[name][0]) / widths[name]
                       for name in NAMES])
        rewards.append(_finite_number(reward, "trial reward"))
    x = np.column_stack([np.ones(len(x_rows)), np.asarray(x_rows)])
    y = np.asarray(rewards)
    penalty = np.eye(x.shape[1]) * 1.0
    penalty[0, 0] = 0.0
    coef = np.linalg.solve(x.T @ x + penalty, x.T @ y)
    suggestion = {}
    for index, name in enumerate(NAMES):
        lo, hi = RANGES[name]
        step = max(-1.0, min(1.0, float(coef[index + 1]))) * step_fraction * widths[name]
        value = min(hi, max(lo, float(base[name]) + step))
        if abs(value - float(base[name])) > 1e-12:
            suggestion[name] = value
    return suggestion


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--profile", default="red")
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("init")
    sub.add_parser("status")
    ingest_log = sub.add_parser("ingest-nav-log")
    ingest_log.add_argument("log", type=Path)
    ingest_log.add_argument("--map-sha", required=True)
    ingest_log.add_argument("--scope", required=True)
    ingest_log.add_argument("--pace", default="unknown")
    ingest_edge = sub.add_parser("ingest-edge-log")
    ingest_edge.add_argument("log", type=Path)
    ingest_edge.add_argument("--map-sha", required=True)
    ingest_edge.add_argument("--scope", required=True)
    ingest_edge.add_argument("--pace", default="unknown")
    ingest_file = sub.add_parser("ingest-nav-file")
    ingest_file.add_argument("nav", type=Path)
    ingest_file.add_argument("--map-sha", required=True)
    ingest_file.add_argument("--scope", required=True)
    ingest_file.add_argument("--pace", default="unknown")
    ingest_match = sub.add_parser("ingest-match")
    ingest_match.add_argument("log", type=Path)
    ingest_match.add_argument("--map-sha", required=True)
    ingest_match.add_argument("--scope", required=True)
    ingest_match.add_argument("--pace", default="unknown")
    ingest_match.add_argument("--build", default="")
    ingest_match.add_argument("--window", type=float, default=5.0)
    cycle = sub.add_parser("cycle")
    cycle.add_argument("log", type=Path)
    cycle.add_argument("--map-sha", required=True)
    cycle.add_argument("--scope", required=True)
    cycle.add_argument("--pace", default="unknown")
    cycle.add_argument("--build", default="")
    cycle.add_argument("--kind", default="pickup_engage")
    cycle.add_argument("--features", required=True)
    cycle.add_argument("--out", type=Path, required=True)
    cycle.add_argument("--temperature", type=float, default=1.0)
    ingest_decisions = sub.add_parser("ingest-decisions")
    ingest_decisions.add_argument("log", type=Path)
    ingest_decisions.add_argument("--map-sha", required=True)
    ingest_decisions.add_argument("--scope", required=True)
    ingest_decisions.add_argument("--pace", default="unknown")
    ingest_decisions.add_argument("--build", default="")
    train_decision = sub.add_parser("train-decision")
    train_decision.add_argument("--kind", required=True)
    train_decision.add_argument("--features", required=True,
                                help="Comma-separated ledger feature names")
    train_decision.add_argument("--out", type=Path, required=True)
    train_decision.add_argument("--outcome-weighted", action="store_true",
                                help="Weight by observed outcome advantage (AWR)")
    train_decision.add_argument("--temperature", type=float, default=1.0)
    qualify = sub.add_parser("qualify-decision")
    qualify.add_argument("--kind", required=True)
    qualify.add_argument("--model", type=Path, required=True)
    qualify.add_argument("--min-rows", type=int, default=50)
    qualify.add_argument("--min-balanced-accuracy", type=float, default=0.7)
    import_coach = sub.add_parser("import-coach")
    import_coach.add_argument("memory", type=Path)
    export_coach = sub.add_parser("export-coach")
    export_coach.add_argument("--out", type=Path)
    export_red = sub.add_parser("export-red")
    export_red.add_argument("model", type=Path, help="Decision model JSON over DUEL_FEATURES")
    export_red.add_argument("--out", type=Path, required=True)
    train = sub.add_parser("train-edge")
    train.add_argument("--out", type=Path, required=True)
    train.add_argument("--native-out", type=Path,
                       help="Also write ADJOIN_EDGE_V1 text for JK_BOT_EDGE_MODEL")
    register = sub.add_parser("register")
    register.add_argument("model", type=Path)
    register.add_argument("--kind", required=True)
    register.add_argument("--scope", required=True)
    promote = sub.add_parser("promote")
    promote.add_argument("sha256")
    promote.add_argument("--safety-ok", action="store_true")
    promote.add_argument("--heldout-ok", action="store_true")
    args = parser.parse_args(argv)
    store = BrainStore(args.root, args.profile)
    try:
        if args.action == "init":
            print(f"brain ready profile={args.profile} root={args.root}")
        elif args.action == "status":
            print(json.dumps({"decisions": len(store.decisions()),
                              "edges": len(store.edge_rows()),
                              "active": store.manifest["active"],
                              "models": len(store.manifest["models"])},
                             indent=2, sort_keys=True))
        elif args.action == "ingest-nav-log":
            print(store.ingest_nav_log(args.log.read_text(encoding="utf-8", errors="replace"),
                                       args.map_sha, args.scope, pace=args.pace))
        elif args.action == "ingest-edge-log":
            print(store.ingest_edge_log(args.log.read_text(encoding="utf-8", errors="replace"),
                                        args.map_sha, args.scope, pace=args.pace))
        elif args.action == "ingest-nav-file":
            print(store.ingest_nav_file(args.nav, args.map_sha, args.scope, pace=args.pace))
        elif args.action == "ingest-match":
            print(ingest_match_log(
                store, args.log.read_text(encoding="utf-8", errors="replace"),
                args.map_sha, args.scope, pace=args.pace, build=args.build,
                window=args.window))
        elif args.action == "cycle":
            text = args.log.read_text(encoding="utf-8", errors="replace")
            counts = ingest_match_log(store, text, args.map_sha, args.scope,
                                      pace=args.pace, build=args.build)
            features = [n.strip() for n in args.features.split(",") if n.strip()]
            model = train_outcome_from_store(store, args.kind, features,
                                             temperature=args.temperature)
            digest = save_decision_model(model, args.out)
            verdict = qualify_decision_candidate(store, args.kind, model)
            print(json.dumps({"ingested": counts, "model_sha256": digest,
                              "qualify": verdict}, indent=2, sort_keys=True))
        elif args.action == "ingest-decisions":
            text = args.log.read_text(encoding="utf-8", errors="replace")
            print(ingest_decision_log(store, text, args.map_sha, args.scope,
                                      pace=args.pace, build=args.build) |
                  {"pickup_engage": ingest_duel_log(
                      store, text, args.map_sha, args.scope,
                      pace=args.pace, build=args.build),
                   "bot_decision": ingest_bot_decision_log(
                      store, text, args.map_sha, args.scope,
                      pace=args.pace, build=args.build)})
        elif args.action == "train-decision":
            features = [name.strip() for name in args.features.split(",") if name.strip()]
            if args.outcome_weighted:
                model = train_outcome_from_store(store, args.kind, features,
                                                 temperature=args.temperature)
            else:
                model = train_decision_from_store(store, args.kind, features)
            print(save_decision_model(model, args.out))
        elif args.action == "qualify-decision":
            model = load_decision_model(args.model)
            print(json.dumps(qualify_decision_candidate(
                store, args.kind, model, min_rows=args.min_rows,
                min_balanced_accuracy=args.min_balanced_accuracy),
                indent=2, sort_keys=True))
        elif args.action == "import-coach":
            print(store.import_coach_memory(
                json.loads(args.memory.read_text(encoding="utf-8"))))
        elif args.action == "export-coach":
            text = json.dumps(store.export_coach_memory(), indent=2, sort_keys=True) + "\n"
            if args.out:
                args.out.write_text(text, encoding="utf-8")
            else:
                print(text, end="")
        elif args.action == "export-red":
            print(export_red_neural(load_decision_model(args.model), args.out))
        elif args.action == "train-edge":
            rows = [(row["features"], row["successes"], row["failures"])
                    for row in store.edge_rows() if row["features"]]
            model = fit_edge_model(rows)
            print(save_edge_model(model, args.out))
            if args.native_out:
                print(export_edge_native(model, args.native_out))
        elif args.action == "register":
            print(store.register_model(args.model, args.kind, args.scope))
        elif args.action == "promote":
            store.promote_model(args.sha256, safety_ok=args.safety_ok,
                                heldout_ok=args.heldout_ok)
            print(f"promoted {args.sha256}")
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


