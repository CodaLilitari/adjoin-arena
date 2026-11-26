"""Lilivane's observation-only Canyon Oasis coach, adapted for ruleset-aware seats."""
import math


class Policy:
    def __init__(self, weapons="guns", dwell=12):
        if weapons not in ("guns", "sabers"):
            raise ValueError("Choose guns or sabers")
        self.weapons = weapons
        self.dwell = dwell
        self.reset()

    def reset(self):
        self.current = None
        self.last = -math.inf

    def choose(self, now, state):
        health, shields, weapon = (state.get(k) for k in ("health", "shields", "weapon"))
        if not all(type(x) in (int, float) and math.isfinite(x) for x in (health, shields, weapon)):
            return None
        if health <= 0 or now - self.last < self.dwell:
            return None
        if health <= 35 or (health <= 65 and shields <= 15):
            wanted = "standoff"
        elif self.current == "standoff" and (health < 90 or shields < 60):
            wanted = "standoff"
        elif self.weapons == "guns" and weapon in (0, 1, 2):
            wanted = "arsenal"
        else:
            wanted = "default"
        return wanted if wanted != self.current else None

    def applied(self, now, preset):
        self.last, self.current = now, preset
