"""Exercise the native recorder startup handoff without launching game processes."""
import io
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch

from scripts.bot_development.legacy import record_server as recorder


class RecorderStartupTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.out = self.root / "run"
        self.out.mkdir()
        self.release = threading.Event()
        self.enterContext(patch.object(recorder.secrets, "token_urlsafe", return_value="local-unit-test-value"))
        self.popen = self.enterContext(patch.object(recorder.subprocess, "Popen"))
        self.child = self.popen.return_value
        self.child.pid = 42
        self.closed = threading.Event()
        self.obs = MagicMock()
        self.obs.prepare_launch.return_value = ()
        self.obs.spawned.side_effect = OSError("observer setup failure")
        async def close():
            self.closed.set()
        self.obs.close = close
        self.enterContext(patch("manager.spectator.SpectatorController", return_value=self.obs))
        self.addCleanup(self.finish)

    def finish(self):
        self.release.set()
        try:
            recorder.finish()
        except (RuntimeError, OSError, TimeoutError):
            pass

    def launch(self):
        return recorder.boot_server([sys.executable], self.root, {}, io.BytesIO(),
                                    Path(__file__).resolve().parents[1], self.out)

    def test_post_spawn_observer_failure_leaves_child_in_callers_hands(self):
        self.assertIs(self.launch(), self.child)
        with self.assertRaises(RuntimeError):
            recorder.finish()
        self.assertTrue(self.closed.is_set())
        self.popen.assert_called_once()

    def test_slow_preparation_cannot_spawn_a_host_after_timeout(self):
        waiting = threading.Event()
        def delayed(env):
            waiting.set()
            if not self.release.wait(timeout=4):
                raise AssertionError("test did not release the observer")
            return ()
        self.obs.prepare_launch.side_effect = delayed
        with patch.object(recorder, "PREPARE_TIMEOUT", .03):
            with self.assertRaises(TimeoutError):
                self.launch()
        self.assertTrue(waiting.wait(2))
        self.release.set()
        with self.assertRaises(RuntimeError):
            recorder.finish()
        self.popen.assert_not_called()
        self.assertTrue(self.closed.is_set())

    def test_failed_spawn_closes_prepared_channels(self):
        self.popen.side_effect = OSError("cannot start host")
        with self.assertRaises(OSError):
            self.launch()
        with self.assertRaises(RuntimeError):
            recorder.finish()
        self.obs.spawned.assert_not_called()
        self.assertTrue(self.closed.is_set())


if __name__ == "__main__":
    unittest.main()
