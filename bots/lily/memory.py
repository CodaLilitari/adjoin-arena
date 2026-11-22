"""Durable outcome evidence keyed by geometry, independently of native node IDs."""
import json
import math
import sqlite3


def packed(value):
    return json.dumps(value, separators=(",", ":"), sort_keys=True, allow_nan=False)


def geometry(environment, position, direction):
    cells = [math.floor(v * 2) for v in position]
    heading = round(math.atan2(direction[1], direction[0]) * 4 / math.pi) % 8
    vertical = 0 if abs(direction[2]) <= .3 * math.hypot(*direction) else (1 if direction[2] > 0 else -1)
    return [environment, cells, heading, vertical]


def route_key(environment, offer, origin):
    position = offer["position"]
    delta = [b - a for a, b in zip(origin, position)]
    return packed(["route", *geometry(environment, position, delta), offer["sector"], offer["class"], offer["item_bin"]])


def skill_key(environment, skill, sense, direction):
    return packed(["motor", *geometry(environment, sense["position"], direction), skill,
                   sense["medium"], bool(sense["supported"])])


def episode_id(record):
    return "/".join(str(record[k]) for k in ("run_id", "world_epoch", "life_epoch", "action_seq"))


class ExperienceStore:
    def __init__(self, path):
        self.db = sqlite3.connect(path, timeout=1)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS attempts (
                episode TEXT PRIMARY KEY, environment_key TEXT NOT NULL,
                identity TEXT NOT NULL, outcome TEXT, success INTEGER, duration REAL
            );
            CREATE INDEX IF NOT EXISTS conditions ON attempts(environment_key, success);
            CREATE TABLE IF NOT EXISTS transitions (
                episode TEXT NOT NULL, phase TEXT NOT NULL, evidence TEXT NOT NULL,
                PRIMARY KEY (episode, phase)
            );
        """)

    def begin(self, attempt):
        episode = episode_id(attempt)
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO attempts(episode,environment_key,identity) VALUES(?,?,?)",
                            (episode, attempt["key"], packed(attempt)))
        return episode

    def transition(self, episode, progress):
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO transitions VALUES(?,?,?)",
                            (episode, progress["phase"], packed(progress)))

    def finish(self, episode, outcome):
        success = outcome["physical_success"]
        if success is not None and type(success) is not bool:
            raise ValueError("Expected a physical verdict or null.")
        with self.db:
            updated = self.db.execute(
                "UPDATE attempts SET outcome=?,success=?,duration=? WHERE episode=? AND outcome IS NULL",
                (packed(outcome), success, outcome["duration_seconds"], episode))
        return updated.rowcount == 1

    def recover(self, run_id):
        """Only the new, exclusive controller calls this after acquiring a lease."""
        lost = {"status": "owner_lost", "physical_success": None, "duration_seconds": None,
                "applied_ms": None, "damage": None, "item_gain": {}}
        with self.db:
            rows = self.db.execute("SELECT episode FROM attempts WHERE instr(episode,?)=1 AND outcome IS NULL",
                                   (run_id + "/",)).fetchall()
            self.db.executemany("UPDATE attempts SET outcome=? WHERE episode=? AND outcome IS NULL",
                                [(packed(lost), eid) for (eid,) in rows])
        return [eid for (eid,) in rows]

    def estimate(self, key):
        attempts, trials, wins, duration = self.db.execute(
            "SELECT count(*),count(success),coalesce(sum(success),0),avg(CASE WHEN success IS NOT NULL THEN duration END) FROM attempts "
            "WHERE environment_key=?", (key,)).fetchone()
        return {"attempts": attempts, "trials": trials, "wins": wins, "probability": (wins + 1) / (trials + 2),
                "mean_seconds": duration}

    def close(self):
        self.db.close()
