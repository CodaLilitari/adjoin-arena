import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from scripts.bot_development.nf_crossover import audit, coverage
from scripts.bot_development.analysis.red_tactical_policy import Model


class NfCrossoverAuditTest(unittest.TestCase):
    def test_replays_weights_and_credits_delivered_axis_only(self):
        weights = Path(__file__).resolve().parents[1] / "bots/models/red_pickup_ffa_guns_noforce_v1.weights"
        data = weights.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        label = Model.decode(data).predict((0,) * 9)
        action = "pickup" if label else "engage"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            native = {}
            models = {}
            files = {}
            roles = {k: {"first": {"game_ms": 100, "rate": 1}, "last": {"game_ms": 1100, "rate": 1},
                         "observed_rate": 1.0} for k in ("dark", "light", "host")}
            for role in ("dark", "light"):
                model = digest if role == "dark" else "teacher"
                context = {"scope": "ffa/guns/noforce", "map_sha": "abc", "scope_match": int(role == "dark")}
                native[role] = {"contexts": [context]}
                models[role] = {"events": {"BOT_RED_MODEL": {"model": model, "status": "ready"}}}
                lines = ["BOT_RED_STATE game_ms=102 kills=0 deaths=0 life=1 dead=0 weapons=0x406",
                         "BOT_STATUS t=.13 pos=1,0,0", "BOT_STATUS t=.3 pos=1.2,0,0",
                         "BOT_DUEL t=.4 seq=1 life=1 target=2 item=5 f=0,0,0,0,0,0,0,0,0 "
                         f"teacher={label} selected={label} applied={label} owner={'supply' if label else 'engage'} "
                         f"model={model} forward=1 slide=0 fire1=0 fire2=0 game_ms=400",
                         "BOT_RED_READ t=.4 life=1 seq=1 axis=forward value=1 game_ms=400"]
                (root / (role + ".log")).write_text("\n".join(lines) + "\n")
            (root / "server.log").write_text("")
            for name in ("dark.log", "light.log", "server.log"):
                files[name] = hashlib.sha256((root / name).read_bytes()).hexdigest()
            raw = {"status": "live_join_and_loadout_verified", "seat_order": ["jan_ors", "boba_fett"],
                   "log_sha256": files, "bots": {side: {"first_stars": [0] * 14} for side in models},
                   "mode_transfer": {"mode": "ffa", "weapons": "guns", "force": "off", "native": {"owners": native},
                                     "content": {"map": "m2.jkl", "map_sha256": "abc"},
                                     "policy_selection": {"controller": "learned", "sha256": digest}},
                   "pace_experiment": {"speed": 1, "requested_game_seconds": 1, "roles": roles},
                   "red_policy": {"model_side": "dark", "weights_sha256": digest, "build": {"binary_sha256": "fixture"},
                                  "start_and_outcomes": {"owners": models}}}
            (root / "receipt.json").write_text(json.dumps(raw))
            with self.assertRaisesRegex(ValueError, "weights digest"):
                audit([root], weights, "wrong-digest", {"m2.jkl": "abc"}, 1)
            report = audit([root], weights, digest, {"m2.jkl": "abc"}, 1)
            self.assertEqual(report["matches"][0]["delivered_nonzero_axis"][action], 1)
            self.assertEqual(report["matches"][0]["same_life_positions_changed"], 1)
            self.assertEqual(len(report["coverage"]["m2.jkl"]["missing_cells"]), 3)
            raw["pace_experiment"]["roles"]["dark"]["observed_rate"] = .83
            (root / "receipt.json").write_text(json.dumps(raw))
            rejected = audit([root], weights, digest, {"m2.jkl": "abc"}, 1)["matches"][0]
            self.assertEqual(rejected["status"], "rejected")
            self.assertIn("outside 1x", rejected["failure"])

    def test_failed_only_map_stays_visible(self):
        report = coverage([{"status": "failed", "failure": "clock"}], {"m2.jkl": "abc"})
        self.assertEqual(len(report["m2.jkl"]["missing_movement_cells"]), 4)
