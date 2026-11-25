import unittest
from unittest.mock import patch

from scripts.bot_development.analysis import start_crossover


def records(assignments):
    return [(dict(assignment=side, logs_sha256={"server.log": str(i)}),
             dict(variant_gob_sha256=side), dict(requested_match_seconds=22))
            for i, side in enumerate(assignments)]


class CrossoverTests(unittest.TestCase):
    def compare(self, runs):
        with patch.object(start_crossover, "read_match", side_effect=runs):
            return start_crossover.compare(range(len(runs)))

    def test_preserves_counterbalanced_order(self):
        sides = ["normal", "swapped", "swapped", "normal"]
        self.assertEqual([r["assignment"] for r in self.compare(records(sides))["runs"]], sides)

    def test_requires_two_independent_repeats_per_condition(self):
        with self.assertRaisesRegex(ValueError, "equal numbers"):
            self.compare(records(["normal", "normal", "swapped"]))
        runs = records(["normal", "swapped", "swapped", "normal"])
        runs[-1][0]["logs_sha256"] = runs[0][0]["logs_sha256"]
        with self.assertRaisesRegex(ValueError, "reused"):
            self.compare(runs)

    def test_rejects_changed_controls_and_mixed_fixtures(self):
        runs = records(["normal", "swapped", "swapped", "normal"])
        runs[-1][2]["requested_match_seconds"] = 55
        with self.assertRaisesRegex(ValueError, "controls differ"):
            self.compare(runs)
        runs = records(["normal", "swapped", "swapped", "normal"])
        runs[1][1]["variant_gob_sha256"] = "other"
        with self.assertRaisesRegex(ValueError, "Fixture changed"):
            self.compare(runs)
