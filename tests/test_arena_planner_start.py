"""Keep a missing opening distinct from a confirmed direct pickup in the evaluation."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts.bot_development.analysis import planner_start


def measured(qualified, detour, time, correct=True):
    return {"pickup_evidence_status": "qualified" if qualified else "unobserved",
            "different_target_after_release": detour, "expected_weapon_gain_s": time,
            "initial_target_correct": correct}


class PlannerExperimentTests(unittest.TestCase):
    def test_missing_plans_and_pickups_stay_in_the_denominator(self):
        observations = [measured(True, True, 10), measured(True, False, 2), measured(False, None, None, False)]
        summary = planner_start.summarize([{"owners": [o]} for o in observations], 1)
        self.assertEqual(summary["openings"], 3)
        self.assertEqual(summary["correct_initial_target"], 2)
        self.assertEqual(summary["corroborated_expected_pickup"], 2)
        self.assertEqual(summary["post_release_detours"], 1)
        self.assertEqual(summary["expected_weapon_gains"], 2)
        self.assertEqual(summary["median_expected_gain_s"], 6)

    def test_other_target_pickup_cannot_earn_a_direct_expected_pickup(self):
        summary = planner_start.summarize([{"owners": [measured(True, False, None, correct=False)]}], 1)
        self.assertEqual(summary["openings"], 1)
        self.assertEqual(summary["corroborated_expected_pickup"], 0)
        self.assertEqual(summary["expected_weapon_gains"], 0)

    def test_last_pair_excluded_from_main_and_controls_checked(self):
        schedule = json.loads(planner_start.SCHEDULE.read_bytes())["runs"]
        directories = [Path(str(c["index"])) for c in schedule]
        def fixture(directory, cell):
            owner = measured(True, False, 1 if cell["set"] == "main" else 3)
            row = dict(cell, owners=[owner, owner], logs_sha256={"server.log": directory.name})
            return row, {"binary": "same"}, {"layout": cell["starts"]}
        with patch.object(planner_start, "evidence", side_effect=fixture):
            report = planner_start.evaluate(directories)
            for s in report["summary"]:
                expected_n, expected_t = (8, 1) if s["set"] == "main" else (1, 3)
                self.assertEqual(s["first_seat"]["openings"], expected_n)
                self.assertEqual(s["first_seat"]["median_expected_gain_s"], expected_t)
            directories[-1] = directories[0]
            with self.assertRaisesRegex(ValueError, "Reused"):
                planner_start.evaluate(directories)
        def changed(directory, cell):
            row, config, layout = fixture(directory, cell)
            if cell["mode"] == "on":
                config["binary"] = "other"
            return row, config, layout
        with patch.object(planner_start, "evidence", side_effect=changed):
            with self.assertRaisesRegex(ValueError, "matched settings"):
                planner_start.evaluate(directories)
