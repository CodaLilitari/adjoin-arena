"""Check camera selection at the native duel launcher entry point."""
from contextlib import nullcontext, redirect_stderr, redirect_stdout
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts.bot_development.legacy import native_force_observation as launcher
from scripts.bot_development.legacy import record_server


class CameraSelectionTests(unittest.TestCase):
    def invoke(self, args):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            argv = ["native_force_observation.py", "--repo", str(base / "source"),
                    "--data", str(base / "game"), "--output", str(base / "out"), *args]
            with patch.object(sys, "argv", argv), patch.dict(sys.modules, record_server=record_server), \
                 patch.object(launcher, "run") as run, patch.object(launcher, "shutdown"), \
                 patch.object(launcher, "signal"), patch.object(launcher.os, "umask"), \
                 patch.object(launcher.tempfile, "TemporaryDirectory", return_value=nullcontext(base)), \
                 redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(launcher.main(), 0)
                return run.call_args.args[0]

    def test_stock_launch_is_unrecorded_by_default(self):
        self.assertIsNone(self.invoke([]).recorder)

    def test_record_defaults_to_follow(self):
        args = self.invoke(["--arena-baseline", "--record"])
        self.assertEqual(args.camera, "follow")
        self.assertIs(args.recorder, record_server)

    def test_rifle_overlook_selects_recording_and_requires_canyon(self):
        args = self.invoke(["--arena-baseline", "--map", "m10.jkl", "--camera", "rifle-overlook"])
        self.assertEqual(args.camera, "rifle-overlook")
        self.assertIs(args.recorder, record_server)
        with self.assertRaises(SystemExit) as invalid:
            self.invoke(["--arena-baseline", "--map", "m2.jkl", "--camera", "rifle-overlook"])
        self.assertEqual(invalid.exception.code, 2)
