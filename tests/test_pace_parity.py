"""Contract tests for the one-actor pacing evidence; the live fixture is separate."""
import copy
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

REPLAY = Path(__file__).resolve().parents[1] / "native/tests/stock_water_replay"
sys.path.insert(0, str(REPLAY))
import pace_parity as pace


def records():
    """Ten 25 ms control ticks. Physics completes the 38th supported step on the last tick."""
    rows = []
    step = 0
    for tick in range(11):
        if step == 38:
            break
        end = min(38, int((tick + 1) * .025 * 150 + .5))
        base = dict(tick=tick, sector=10, attached_sector=10, attached_surface=7, attach_flags=1,
                    physics_flags=0, actor_flags=0, thing_flags=0, endurance=0, owner="baseline",
                    wet=False, water_surface=False, position=["0x0p+0"] * 3, velocity=["0x0p+0"] * 3,
                    facing=["0x0p+0", "0x1p+0", "0x0p+0"], up=["0x0p+0", "0x0p+0", "0x1p+0"],
                    health="0x1.9p+6", head_pitch="0x0p+0")
        rows.append(dict(base, kind="control", stage="inputs", step=step, streak=step))
        while step < end:
            step += 1
            rows.append(dict(base, kind="step", stage="integrated", step=step, streak=step))
    rows.append(dict(rows[-1], kind="terminal", result="supported_dry"))
    return rows


def write_rows(path, rows):
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


class PaceParityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.native = dict(physics_steps=38, control_ticks=10, sector=10, health=100,
                           terminal="supported_dry")

    def validate(self, rows):
        path = self.root / "pace.jsonl"
        write_rows(path, rows)
        return pace.validate_pace(path, self.native, .025)

    def test_complete_physics_and_control_evidence(self):
        self.assertEqual(len(self.validate(records())), 64)
        self.assertEqual(pace.known_case("pool-90", 0)[1]["corrected_dry_s"], 10.72)
        with self.assertRaises(ValueError):
            pace.known_case("pool-90", 45)

    def test_rejects_truncated_duplicate_or_zero_work(self):
        rows = records()
        for broken in ([], rows[:-1], [rows[-1]], [*rows[:6], *rows[7:]],
                       [*rows[:6], rows[5], *rows[6:]], [*rows, rows[-1]]):
            with self.subTest(size=len(broken)), self.assertRaises(ValueError):
                self.validate(broken)

    def test_rejects_bad_state_types_and_contact(self):
        for key, bad in (("step", True), ("actor_flags", False), ("physics_flags", 4.1),
                         ("position", [0, 1, 2]), ("facing", ["nan"] * 3), ("up", []),
                         ("water_surface", 0), ("attached_surface", -1), ("streak", 37)):
            rows = records()
            rows[1][key] = bad
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.validate(rows)

    def test_terminal_is_same_last_observation_and_physical_result(self):
        for key, bad in (("result", "sim_timeout"), ("tick", 4), ("wet", True),
                         ("health", "0x2p+0"), ("position", ["0x1p+0"] * 3)):
            rows = records()
            rows[-1][key] = bad
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.validate(rows)
        self.native["physics_steps"] = 39
        with self.assertRaises(ValueError):
            self.validate(records())

    def test_first_divergence_names_field_and_substep(self):
        a, b = self.root / "a", self.root / "b"
        a.mkdir()
        b.mkdir()
        baseline = records()
        changed = copy.deepcopy(baseline)
        changed[2]["position"] = ["0x1p+0", *changed[2]["position"][1:]]
        for folder, rows in ((a, baseline), (b, changed)):
            write_rows(folder / "pace.jsonl", rows)
        result = pace.first_difference(a, b, partial=True)
        self.assertEqual((result["file"], result["field"], result["tick"], result["step"]),
                         ("pace.jsonl", "position[0]", 0, 2))

    def test_paced_shortcut_and_overlapping_timings(self):
        with self.assertRaises(ValueError):
            pace.check_pacing(.1, 100, .04, True)
        pace.check_pacing(.1, 100, .04, False)
        samples = [dict(mode=m, wall_seconds=s) for m,s in
                   (("1x", 4.), ("1x", 5.), ("uncapped", 2.), ("uncapped", 4.5))]
        self.assertEqual(pace.summarize_times(samples)["acceleration"], "inconclusive")
        samples[-1]["wall_seconds"] = 1.
        self.assertEqual(pace.summarize_times(samples)["minimum_observed_ratio"], 2.)

    def test_nonzero_process_cannot_qualify(self):
        row, expected = pace.known_case("pool-90", 0)
        with patch.object(pace.subprocess, "run", return_value=pace.subprocess.CompletedProcess([], 1)):
            with self.assertRaisesRegex(ValueError, "exit 1"):
                pace.run_sample(self.root / "trial", Path("unused"), Path("unused"), row, 0,
                                expected, False, {})

    def run_with_samples(self, fail_second):
        calls = []
        def sample(folder, executable, geometry, row, yaw, expected, paced, summary):
            folder.mkdir()
            calls.append(summary["mode"])
            rows = records()
            if fail_second and len(calls) == 2:
                rows[2]["physics_flags"] = 99
                write_rows(folder / "pace.jsonl", rows)
                raise ValueError("test landing failed")
            for name in pace.LOGS:
                write_rows(folder / name, rows if name == "pace.jsonl" else [{"event": "stub"}])
            summary["wall_seconds"] = 10. if paced else 1.

        args = SimpleNamespace(output=self.root / "trial", samples=2, case="pool-90", yaw=0)
        with patch.object(pace, "prepare_build", return_value=(None, None, {})), \
             patch.object(pace, "run_sample", side_effect=sample):
            outcome = pace.run(args)
        return calls, outcome, json.loads((args.output / "receipt.json").read_bytes())

    def test_driver_runs_paced_controls_first(self):
        calls, passed, receipt = self.run_with_samples(False)
        self.assertEqual(calls, ["1x", "1x", "uncapped", "uncapped"])
        self.assertTrue(passed)
        self.assertEqual(receipt["trajectory_parity"], "passed")
        self.assertEqual(receipt["acceleration"], "observed")

    def test_failed_repeated_control_stops_and_keeps_first_divergence(self):
        calls, passed, receipt = self.run_with_samples(True)
        self.assertEqual(calls, ["1x", "1x"])
        self.assertFalse(passed)
        self.assertIn("test landing failed", receipt["error"])
        self.assertEqual(receipt["first_difference"]["field"], "physics_flags")
        self.assertEqual(receipt["first_difference"]["step"], 2)


if __name__ == "__main__":
    unittest.main()
