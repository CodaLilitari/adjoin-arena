"""Online route reliability for ordinary seats. Only engine edge outcomes update it."""
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
from contextlib import closing

from .brain import EDGE_FEATURES, edge_native_bytes

# Fixed physical scales keep inference stable between visits and on unseen graphs.
SCALES = (2., 1., 1., 8., 1., 1., 1., 4., 12., 12.)
ATTEMPT = re.compile(r"BOT_EDGE_ATTEMPT name=(.{1,64}?) t=[0-9.]+ event=(arrive|stall) "
                     r"from_key=[0-9a-f]{1,16} to_key=[0-9a-f]{1,16} edge=(\d{1,2}) "
                     r"dist_mm=(\d{1,7}) dz_mm=(-?\d{1,7}) from_water=([01]) to_water=([01]) "
                     r"dest_item=([01]) base_cost_milli=(\d{1,8}) degree_from=(\d{1,3}) degree_to=(\d{1,3})")


def parse_observation(line, name):
    match = ATTEMPT.fullmatch(line)
    if not match or match[1] != name:
        return None
    mode, dist, dz, wet_a, wet_b, item, cost, degree_a, degree_b = map(int, match.groups()[2:])
    if mode > 64 or abs(dz) > dist + 2 or dist > 1000000 or cost > 10000000:
        return None
    return ((dist/1000, dz/1000, abs(dz)/1000, mode, wet_a, wet_b, item, cost/1000, degree_a, degree_b),
            int(match[2] == "arrive"))


def memory_root():
    override = os.environ.get("ADJOIN_NAV_MEMORY")
    if override == "off":
        return None
    state = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state")
    return Path(override).expanduser().resolve() if override else state / "adjoin-arena/navigation"


def navigation_rules(rank, sabers_only, force_enabled):
    """Only ranks 0 and 8, or explicitly disabled Force, have a matching bank."""
    if force_enabled and rank not in (0, 8):
        return None
    return ("ff" if force_enabled and rank else "nf") + ("-sabers" if sabers_only else "-guns")


class LiveNavigationMemory:
    """Partition one native log by the behavior the engine actually applied."""

    def __init__(self, root, profile, build, rank):
        self.root, self.profile, self.build, self.rank = root, profile, build, rank
        # Bot_ReloadBehavior emits an event only if it changes these engine defaults.
        self.rules = navigation_rules(rank, False, True)
        self.banks = {}
        self.saved = {}
        self.sequence = 0

    def bank(self, rules):
        if rules not in self.banks:
            self.banks[rules] = NavigationMemory(self.root, self.profile, self.build, rules)
        return self.banks[rules]

    def observe(self, session, start, tagged):
        if start > self.sequence + 1:
            raise ValueError("Navigation observation sequence has a gap")
        fresh = tagged[max(0, self.sequence - start + 1):]
        groups = {}
        for rules, observation in fresh:
            groups.setdefault(rules, []).append(observation)
        for rules, group in groups.items():
            self.bank(rules).observe(session, self.saved.get(rules, 0) + 1, group)
        # If a later bank was busy, the existing SQLite sequence check makes a
        # retry of the first bank idempotent. Advance only after all commits.
        for rules, group in groups.items():
            self.saved[rules] = self.saved.get(rules, 0) + len(group)
        self.sequence += len(fresh)


class NavigationMemory:
    """Transactional, bounded-cost route priors scoped by seat and engine identity."""

    def __init__(self, root, profile, build, rules=None):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", profile) or not re.fullmatch("[0-9a-f]{64}", build):
            raise ValueError("Invalid navigation memory identity")
        self.directory = Path(root) / build / profile
        if rules is not None:
            if rules not in ("nf-guns", "nf-sabers", "ff-guns", "ff-sabers"):
                raise ValueError("Invalid navigation rules")
            self.directory /= rules
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.db = self.directory / "weights.sqlite3"
        with closing(sqlite3.connect(self.db)) as connection, connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS model (
                    id INTEGER PRIMARY KEY CHECK (id=1), steps INTEGER NOT NULL,
                    weights TEXT NOT NULL, bias REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, seq INTEGER NOT NULL);
            """)

    def observe(self, session, start, observations):
        if not observations:
            return
        if start < 1 or not 1 <= len(session) <= 128:
            raise ValueError("Invalid observation sequence")
        # The native supervisor calls this synchronously. Retry a busy writer
        # from the delivery queue without holding the roster monitor for seconds.
        with closing(sqlite3.connect(self.db, timeout=.05)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT seq FROM sessions WHERE id=?", (session,)).fetchone()
            previous = row[0] if row else 0
            if start > previous + 1:
                raise ValueError("Navigation observation sequence has a gap")
            fresh = observations[max(0, previous-start+1):]
            if not fresh:
                return
            row = db.execute("SELECT steps, weights, bias FROM model WHERE id=1").fetchone()
            steps, weights, bias = (row[0], json.loads(row[1]), row[2]) if row else (0, [0.] * 10, 2.)
            initial_steps = steps
            for observation in fresh:
                # Invalid browser rows still consume their wire sequence number.
                if observation is None:
                    continue
                features, success = observation
                x = [v/s for v,s in zip(features, SCALES)]
                score = max(-30., min(30., bias + sum(a*b for a,b in zip(weights, x))))
                # Normalized SGD bounds the influence of an unusually long edge.
                delta = .16 * (success - 1/(1+math.exp(-score))) / (1+sum(v*v for v in x))
                weights = [max(-2., min(2., w*.99995 + delta*v)) for w,v in zip(weights, x)]
                bias = max(-3., min(4., bias+delta))
                steps += 1
            if steps > initial_steps:
                db.execute("INSERT OR REPLACE INTO model VALUES(1,?,?,?)", (steps,json.dumps(weights),bias))
            db.execute("INSERT OR REPLACE INTO sessions VALUES(?,?)", (session,start+len(observations)-1))

    def snapshot(self):
        with closing(sqlite3.connect(self.db)) as connection:
            row = connection.execute("SELECT steps, weights, bias FROM model WHERE id=1").fetchone()
        if not row:
            return None
        raw = edge_native_bytes(dict(schema=1, features=list(EDGE_FEATURES), centers=[0.]*10,
                                     scales=list(SCALES), weights=json.loads(row[1]), bias=row[2]))
        return raw.decode("ascii"), hashlib.sha256(raw).hexdigest(), row[0]

