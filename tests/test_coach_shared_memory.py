"""Two live auto coaches can begin with the same SQLite snapshot."""
from contextlib import ExitStack
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from bots import coach, coach_seat
from bots.brain import BrainStore
from tests.test_coach_seat import FakeHub


class SharedCoachMemory(unittest.TestCase):
    def test_next_choice_includes_a_window_graded_by_the_other_seat(self):
        with tempfile.TemporaryDirectory() as root, ExitStack() as stack:
            stores = [BrainStore(Path(root), "coach") for _ in range(2)]
            for store in stores:
                stack.callback(store.close)
            a, b = [coach.BrainBandit(["default", "hunter"], s, "JHS", "A") for s in stores]
            b.record("hunter", -1.0)
            a.record("default", 1.0)
            self.assertEqual(a.choose(), "default")
            self.assertEqual(a.export(), {"default": {"plays": 1, "total": 1.0},
                                          "hunter": {"plays": 1, "total": -1.0}})

    def test_both_entry_points_keep_windows_from_the_same_starting_snapshot(self):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            root = Path(directory) / "brain"
            args = ["--brain-root", str(root), "--label", "JHS", "--build-id", "competitive",
                    "--credentials", "unused", "--presets", "default", "--dwell-seconds", "90"]
            stack.enter_context(patch.object(coach, "load_private", return_value={}))
            stack.enter_context(patch.object(coach_seat, "load_private", return_value={}))
            stack.enter_context(patch.object(coach_seat.signal, "signal"))
            real_session = coach.session

            def grade_seat(seat, **_):
                hub = FakeHub()
                seat.request, seat.clock, seat.out = hub.request, lambda: now, lambda message: None
                now = 0
                seat.tick()       # attach, send preset
                seat.tick()       # acknowledge
                now, hub.kills = 90, 3
                seat.tick()       # +2.0 on the default preset
                seat.tick()       # no second grade without a new window

            def grade_standalone(cred, agent, **kwargs):
                # Its initial read has completed. Let the second connection
                # grade first, while the first one still holds its old scores.
                self.assertEqual(coach_seat.main(args), 0)
                hub = FakeHub()
                now = 0.0

                def sleep(dt):
                    nonlocal now
                    now += dt
                    if now >= 95:
                        hub.deaths = 3

                kwargs.update(clock=lambda: now, sleep=sleep, seconds=100, poll=5,
                              request=hub.request, log=lambda message: None)
                real_session(cred, agent, **kwargs)  # -2.0 on the same preset

            stack.enter_context(patch.object(coach_seat, "run", side_effect=grade_seat))
            stack.enter_context(patch.object(coach, "session", side_effect=grade_standalone))
            self.assertEqual(coach.main(args), 0)
            store = BrainStore(root, "coach")
            try:
                self.assertEqual(store.coach_arms("JHS", "competitive"),
                                 {"default": {"plays": 2, "total": 0.0}})
                self.assertEqual(store.coach_arms("JHS", "older"), {})
            finally:
                store.close()
