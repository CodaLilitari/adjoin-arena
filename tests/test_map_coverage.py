import unittest
from pathlib import Path

from scripts.bot_development.map_coverage import schedule
from scripts.bot_development.score_map_coverage import owner_activity
from scripts.bot_development.score_cross_runtime_coverage import score


class MapCoverageTests(unittest.TestCase):
    def test_browser_activity_and_wire_mode_must_share_a_jhs_run(self):
        qa = Path(__file__).resolve().parents[1] / "qa"
        receipt = score(qa / "map-rules-play.json", qa / "windows-stock-ctf-c2-c3.json",
                        qa / "jhs-ffa-owners.json")
        trials = receipt["jhs_browser_trials"]
        opening = trials["jhs-ff-sabers-front-edge"]
        repeat = trials["jhs-ff-sabers-room-flags"]
        self.assertTrue(opening["both_moving"])
        self.assertFalse(opening["verified_ffa"])
        self.assertTrue(repeat["verified_ffa"])
        self.assertFalse(repeat["both_moving"])
        self.assertFalse(any(t["verified_ffa_both_moving"] for t in (opening, repeat)))

    def test_all_legal_cells_are_unique(self):
        cells = schedule()
        self.assertEqual(len({c["key"] for c in cells}), 68)
        groups = {(c["episode"], c["mode"]) for c in cells}
        self.assertEqual(groups, {("jk1mp", "ffa"), ("jk1mp", "tdm"), ("jk1ctf", "ctf"),
                                  ("jhs", "ffa"), ("jhs", "tdm")})
        for level in {c["map"] for c in cells}:
            self.assertEqual({(c["weapons"], c["force"]) for c in cells if c["map"] == level},
                             {("guns", "off"), ("guns", "on"), ("sabers", "off"), ("sabers", "on")})

    def test_ascent_must_be_in_window_and_in_one_life(self):
        def nav(time, sector):
            return (f"BOT_RED_NAV t={time} scope=ffa/guns/force ready=1 nodes=5 edges=9 sector={sector}"
                    " fwd=1 slide=0 fire=0,0 objective_valid=0")

        def observe(rows):
            return owner_activity(rows, {"first": {"game_ms": 1000}}, 2, "ffa/guns/force", True)

        first = "BOT_RED_STATE life=1 dead=0 hp=100"
        respawn = "BOT_RED_FIRST life=2"
        result = observe([first, nav(.9, 124), nav(1.0, 119), respawn, nav(1.2, 58), nav(1.4, 58), nav(3, 0)])
        self.assertEqual(result["same_life_sector_changes"], 0)
        self.assertEqual(result["visited"], [58, 119])
        self.assertFalse(result["jhs_regions"]["upper_passages"]["arrived_from_lower_in_life"])
        self.assertNotIn("roof", result["jhs_regions"])
        result = observe([first] + [nav(1.0 + .2 * i, s) for i, s in enumerate((124, 122, 121, 120, 123, 119, 58, 58))])
        self.assertEqual(result["consecutive_ascent_sectors"], 7)
        self.assertTrue(result["jhs_regions"]["upper_passages"]["arrived_from_lower_in_life"])


if __name__ == "__main__":
    unittest.main()
