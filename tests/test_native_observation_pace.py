import io
import unittest

from scripts.bot_development.legacy.native_observation_pace import NativePace


class NativeObservationPaceTests(unittest.TestCase):
    def setUp(self):
        self.receipt = {"speed": 2, "requested_game_seconds": 1}
        self.trace = io.StringIO()
        self.clock = NativePace(self.trace, self.receipt)
        self.pids = {"host": 10, "dark": 20, "light": 30}

    def sample(self, role, n, *, hz=2, pid=None, applied=34):
        self.clock.observe(role, self.pids[role],
                           f"ARENA_PACE role={role} pid={pid or self.pids[role]} rate=2 frame={n*5} "
                           f"game_ms={170*n} mono_ns={1000000000+170000000*n//hz} "
                           f"step_ms=34 applied_ms={applied}")

    def start(self):
        self.clock.observe("dark", 20, "BOT_PLANNER_GATE name=A mode=on phase=released slot=1")
        self.clock.observe("light", 30, "BOT_PLANNER_GATE name=B mode=on phase=released slot=2")
        self.clock.observe("host", 10, "GATE_HOST_ACK")
        self.assertFalse(self.clock.poll(10))
        self.assertIsNone(self.clock.start)
        self.clock.observe("host", 10, "GATE_HOST_ACK")
        self.assertFalse(self.clock.poll(1000000000))

    def test_common_post_release_window_and_slowest_role(self):
        self.sample("host", 0)
        self.assertFalse(self.clock.first)
        self.start()
        for n in range(7):
            for role in ("dark", "light"):
                self.sample(role, n)
        self.assertFalse(self.clock.poll(1600000000))
        for n in range(7):
            self.sample("host", n)
        self.assertTrue(self.clock.poll(1600000001))
        self.clock.finish(1600000001)
        for row in self.receipt["roles"].values():
            self.assertEqual(row["observed_rate"], 2)
            self.assertAlmostEqual(row["observed_game_tail_s"], .02)

    def test_one_unaccelerated_owner_invalidates_match(self):
        self.start()
        for role in self.pids:
            for n in range(7):
                self.sample(role, n, hz=1 if role == "dark" else 2)
        with self.assertRaisesRegex(ValueError, "outside_requested_band"):
            self.clock.finish(2200000000)
        self.assertEqual(self.receipt["roles"]["dark"]["observed_rate"], 1)

    def test_rejects_wrong_process_applied_step_and_missing_samples(self):
        self.start()
        with self.assertRaisesRegex(ValueError, "identity"):
            self.sample("host", 0, pid=20)
        with self.assertRaisesRegex(ValueError, "engine_step"):
            self.sample("host", 0, applied=17)
        self.sample("host", 0)
        with self.assertRaisesRegex(ValueError, "missing_or_inconsistent"):
            self.sample("host", 2)
