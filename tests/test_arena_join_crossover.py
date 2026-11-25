import unittest

from scripts.bot_development.analysis import join_crossover as crossover


def series(order, launcher, builder, **config):
    return {"configuration": {"seat_order": list(order), "launcher_sha256": launcher,
                              "ready_gate_source_sha256": {"controlled_opening.py": builder, "ready_gate.py": "gate"},
                              **config},
            "runs": [{"assignment": a} for a in crossover.ASSIGNMENTS]}


class JoinCrossoverTests(unittest.TestCase):
    def test_only_join_order_and_the_two_measurement_tools_can_differ(self):
        boba = crossover.PROFILE_ORDER
        jan = boba[::-1]
        baseline = series(boba, "old launcher", "old builder", engine="same engine")
        repeat = series(jan, "new launcher", "new builder", engine="same engine")
        controls, old = crossover.match_controls(baseline, boba)
        other, new = crossover.match_controls(repeat, jan)
        self.assertEqual(controls, other)
        self.assertNotEqual(old, new)
        repeat["configuration"]["ready_gate_source_sha256"]["ready_gate.py"] = "changed gate"
        self.assertNotEqual(controls, crossover.match_controls(repeat, jan)[0])
        self.assertIn("seat_order", baseline["configuration"])

    def test_requires_physical_sequence_and_explicit_join_order(self):
        boba = crossover.PROFILE_ORDER
        example = series(boba, "launcher", "builder")
        with self.assertRaisesRegex(ValueError, "wrong join order"):
            crossover.match_controls(example, boba[::-1])
        example["runs"][0], example["runs"][1] = example["runs"][1], example["runs"][0]
        with self.assertRaisesRegex(ValueError, "normal, swapped"):
            crossover.match_controls(example, boba)
