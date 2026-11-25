"""Exercise the native recorder startup handoff without launching game processes."""
import io
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from scripts.bot_development.legacy import native_force_observation as launcher
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

    def test_early_clip_cap_stages_all_collected_frames_until_finish(self):
        # Native frame receipt times are 45 seconds apart without requiring a real
        # game or a 45-second test. Encoding must wait for the launcher's finish.
        ipc = MagicMock()
        for name in ("start", "wait_ready", "info", "close"):
            setattr(ipc, name, AsyncMock())
        self.enterContext(patch("web_gateway.ipc.NativeIPC", return_value=ipc))
        self.child.poll.return_value = None
        self.obs.spawned.side_effect = None
        players = [{"slot": 1, "peer_id": 3, "generation": 1}, {"slot": 2, "peer_id": 5, "generation": 1}]
        state = dict(available=True, state="ready", reason="", mode="follow", world_epoch=1, control_epoch=1,
                     players=players, target={"peer_id": 3, "generation": 1}, pose={})
        self.obs.status.return_value = state
        self.obs.configure = AsyncMock(return_value=state)
        self.obs.frame.side_effect = [
            {"sequence": i, "pixels": bytes([i] * 4), "received": stamp, "width": 1, "height": 1}
            for i, stamp in enumerate((1., 2., 46.), start=1)]
        encoded = threading.Event()
        def encode(folder, out, records, filename):
            self.assertEqual(len(records), 3)
            self.assertEqual(len(list(folder.glob("*.png"))), 3)
            encoded.set()
            return {"path": filename}
        self.enterContext(patch.object(recorder, "encode", side_effect=encode))
        self.launch()
        self.assertTrue(self.closed.wait(3))
        self.assertFalse(encoded.is_set())
        recorder.stop_capture()
        self.assertFalse(encoded.is_set())
        self.assertEqual(recorder.finish()["status"], "recorded")
        self.assertTrue(encoded.is_set())

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


class MatchCutoffTests(unittest.TestCase):
    def test_games_exit_before_encode_and_prior_match_failure_survives(self):
        for primary_failed, video_failed in ((False, False), (True, True), (False, True)):
            with self.subTest(primary_failed=primary_failed, video_failed=video_failed), tempfile.TemporaryDirectory() as tmp:
                order = []
                camera = MagicMock()
                camera.stop_capture.side_effect = lambda: order.append("stop capture")
                def finish():
                    order.append("encode")
                    if video_failed:
                        raise RuntimeError("simulated observer failure")
                    return {"status": "recorded", "receipt_sha256": "unit"}
                camera.finish.side_effect = finish
                receipt = {"status": "failed" if primary_failed else "live_join_and_loadout_verified"}
                with patch.object(launcher, "shutdown", side_effect=lambda: order.append("stop native groups")):
                    if video_failed and not primary_failed:
                        with self.assertRaises(RuntimeError):
                            launcher.finish_match(camera, receipt, Path(tmp), preserve_error=False)
                    else:
                        launcher.finish_match(camera, receipt, Path(tmp), preserve_error=primary_failed)
                self.assertEqual(order, ["stop capture", "stop native groups", "encode"])
                self.assertEqual(receipt["observer_status"], "failed" if video_failed else "recorded")
                if primary_failed:
                    self.assertEqual(receipt["match_status"], "failed")


if __name__ == "__main__":
    unittest.main()
