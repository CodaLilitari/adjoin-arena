import unittest
from dataclasses import replace
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.bot_development.analysis.c3_matched_doors import (
    Observation, STARTS, first_life, route_score, score_arm, vector,
)


def observations(seat, sectors):
    slot, team, sector, pose = STARTS[seat]
    home = Observation("C3_MATCH_START_V1", 10, slot, team, 10, sector, pose,
                       (0, 1, 0), 100, (int(team == 1), int(team == 2)), (0, 0))
    return [home] + [replace(home, kind="C3_MATCH_OBS_V1", sector=sector, time=11+i)
                     for i, sector in enumerate(sectors)]


class MatchedDoors(unittest.TestCase):
    def test_native_printvector_console_limit(self):
        self.assertEqual(vector("<-4.378766 -1.480898 -0.064224"), (-4.378766, -1.480898, -.064224))
        with self.assertRaises(ValueError):
            vector("<-4.378766 -1.480898")

    def test_chamber_exit_requires_passing_a_door(self):
        rows = observations("lily", [509, 507, 509, 505, 510, 506, 511])
        self.assertIsNone(route_score("lily", rows[:4])["chamber_clear_observed_by_game_s"])
        score = route_score("lily", first_life("lily", rows))
        self.assertEqual(score["first_sector_exit"], {"to_sector": 509, "observed_by_game_s": 1})
        self.assertEqual(score["witnessed_door_passages_game_s"], {"73_outer": 7})
        self.assertEqual(score["chamber_clear_observed_by_game_s"], 7)

    def test_chamber_clear_when_narrow_door_sector_is_unsampled(self):
        rows = observations("lily", [509, 508, 790])
        score = route_score("lily", rows)
        self.assertEqual(score["witnessed_door_passages_game_s"], {})
        self.assertEqual(score["chamber_clear_observed_by_game_s"], 2)

    def test_respawn_and_death_stop_first_life_even_with_later_flag(self):
        rows = observations("red", [396, 394, 395, 700])
        rows[-1] = replace(rows[-1], flags=(1, 0))
        for death in (dict(kind="C3_MATCH_NEWLIFE_V1"), dict(health=0)):
            life = first_life("red", [*rows[:3], replace(rows[3], **death), rows[-1]])
            score = route_score("red", life)
            self.assertEqual(score["witnessed_door_passages_game_s"], {})
            self.assertIsNone(score["carried_enemy_flag_observed_by_game_s"])
        self.assertEqual(first_life("red", rows, cutoff=13), rows[:3])

    def test_wrong_key_and_duplicate_start_rejected(self):
        rows = observations("red", [])
        with self.assertRaises(ValueError):
            first_life("red", [replace(rows[0], keys=(1, 0))])
        with self.assertRaises(ValueError):
            first_life("red", rows * 2)

    def test_logs_and_common_clock_agree_with_a_live_keyed_door_crossing(self):
        with TemporaryDirectory() as temp:
            arm = Path(temp)
            room = arm / "rooms/headless-fixture"
            room.mkdir(parents=True)
            head = {"hosted": {"map": "c3.jkl"}, "seats": {s: {"joined": True} for s in STARTS}}
            (room / "headless.json").write_text(json.dumps(head))
            (arm / "launcher.log").write_text(
                '{"event":"hosted","joined":true,"mode":"ff-guns"}\n{"event":"playing","seconds":10,"t":9}')
            snapshots = [{"wall": 2000+t, "seats": {s: {"game_time": t, "deaths": 0, "health": 100,
                           "weapon": 10} for s in STARTS}} for t in range(10, 16)]
            (arm / "samples.json").write_text(json.dumps(snapshots))
            for seat, route in (("lily", [509, 507, 508]), ("red", [391, 1, 2])):
                slot, team, *_ = STARTS[seat]
                lines = [f"    5.00 log BOT_JOINED slot={slot} net={slot+1} map=c3.jkl model=ky.3do",
                         f"    5.10 error BOT_CTF_BINDINGS map=c3.jkl red_flag=43 gold_flag=48 red_mark=789 gold_mark=787 team={team}"]
                for row in observations(seat, route):
                    for value in (row.kind, slot, team, row.time, row.sector,
                                  "<%f %f %f>" % row.position, "<0 1 0>", 100, *row.keys, *row.flags):
                        lines.append(f"  {row.time:.2f} log {value}")
                lines += ["  16.00 log You need the Gold key...", "  16.10 log Red Team Captured The Flag!",
                          "  20.00 log Red Team Captured The Flag!"]
                (room / (seat+".console.log")).write_text("\n".join(lines))
            actual = score_arm(arm)
            self.assertEqual(actual["shared_captures"], {"red": 1, "gold": 0})
            self.assertEqual(actual["owners"]["lily"]["witnessed_door_passages_game_s"], {"74_inner": 3})
            self.assertEqual(actual["owners"]["red"]["shared_key_denials"], {"gold": 1})
            self.assertEqual(actual["owners"]["red"]["shared_game_s_per_wall_s"], 1)
