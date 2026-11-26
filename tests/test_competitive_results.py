import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from scripts.bot_development.competitive_results import summarize


class CompetitiveWindowTest(unittest.TestCase):
    def test_samples_across_an_ordinary_respawn_or_outside_window_are_excluded(self):
        def pose(frame, life, time, position, fire="1,0"):
            return (f"BOT_SABER_POSE frame={frame} life={life} game_ms={time} dead=0 xy={position},0 "
                    f"z=0 pitch=5 foe=2 foe_z=.2 foe_vz=.2 fire={fire}\n")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            owners = ("dark", "light")
            text = ("BOT_RED_STATE game_ms=110 kills=2 deaths=0 life=1 dead=0 weapons=0x406\n"
                    + pose(1, 1, 111, 0) + pose(2, 1, 145, .02)
                    + pose(3, 2, 179, .04) + pose(5, 2, 247, .05)
                    + "BOT_RED_STATE game_ms=1200 kills=3 deaths=0 life=2 dead=0 weapons=0x406\n")
            for owner in owners:
                (root / (owner + ".log")).write_text(text)
            (root / "server.log").write_text("ARENA_PACE game_ms=90\nGold Team Captured The Flag!\n"
                                             "ARENA_PACE game_ms=130\nRed Team Captured The Flag!\n"
                                             "Gold Flag has been returned!\nThe Red Flag has been returned!\n")
            receipts = {name + ".log": hashlib.sha256((root / (name + ".log")).read_bytes()).hexdigest()
                        for name in (*owners, "server")}
            row = {"status": "live_join_and_loadout_verified", "log_sha256": receipts,
                   "mode_transfer": {"content": {"map": "c1.jkl", "map_sha256": "fixture"}, "mode": "ctf",
                                     "weapons": "sabers", "force": "off"}, "seat_order": list(owners),
                   "red_policy": {"build": {"binary_sha256": "fixture"}, "model_side": None, "weights_sha256": None},
                   "pace_experiment": {"speed": 1, "requested_game_seconds": 1,
                                       "roles": {role: {"first": {"game_ms": 100}} for role in (*owners, "host")}},
                   "bots": {side: {"first_stars": [0] * 14} for side in owners}}
            (root / "receipt.json").write_text(json.dumps(row))
            observed = summarize(root)
            self.assertEqual(observed["host_captures"], {"red": 1, "gold": 0})
            self.assertEqual(observed["host_flag_returns"], {"red": 1, "gold": 1})
            self.assertEqual(observed["owners"]["dark"]["kills"], 0)
            self.assertEqual(observed["owners"]["dark"]["saber_fire_frame_pairs"], 1)
            self.assertEqual(observed["owners"]["dark"]["saber_fire_frames_xy_over_0.001_units"], 1)
            (root / "dark.log").write_text(text + "changed")
            with self.assertRaisesRegex(ValueError, "digest mismatch"):
                summarize(root)
