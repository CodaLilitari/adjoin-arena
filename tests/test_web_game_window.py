import asyncio
from contextlib import redirect_stderr
import io
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from web_bots import headless


class GameWindowTests(unittest.TestCase):
    def test_compares_each_clock_from_its_own_start(self):
        window = {}
        def step(lily, red):
            return headless.game_window_complete(window, {
                "lily": {"world_epoch": 3, "game_time": lily},
                "red": {"world_epoch": 1, "game_time": red},
            }, 60)
        self.assertFalse(step(49, 17))
        self.assertFalse(step(111, 76))
        self.assertTrue(step(112, 77))
        self.assertEqual(window["red"], {"start": 17, "end": 77, "world_epoch": 1})

    def test_refuses_world_change_and_clock_rollback(self):
        for current in ((1, 9), (2, 12)):
            window = {}
            for i, (epoch, stamp) in enumerate(((1, 10), current)):
                seat = {"red": {"world_epoch": epoch, "game_time": stamp}}
                if not i:
                    self.assertFalse(headless.game_window_complete(window, seat, 3))
                else:
                    with self.assertRaises(ValueError):
                        headless.game_window_complete(window, seat, 3)

    def test_launcher_stops_on_native_time_and_writes_window(self):
        with TemporaryDirectory() as tmp:
            runner = headless.Launcher(SimpleNamespace(runtime=Path(tmp), relay="local", display="headless"))
            host = SimpleNamespace(hub=SimpleNamespace(pump=lambda: None), expire_capture=lambda: None)
            runner.hosts = {"red": host, "lily": host}
            times = {"red": iter((12., 14.)), "lily": iter((44., 46.))}
            runner.seat_status = lambda ident: dict(joined=True, world_epoch=1, game_time=next(times[ident]))
            runner.log = lambda **event: None
            try:
                asyncio.run(runner.pump(headless.time.monotonic()+2, game_seconds=2))
                recorded = runner.manifest["game_window"]
                self.assertEqual(recorded["requested_game_seconds"], 2)
                self.assertEqual(recorded["owners"]["lily"]["end"], 46)
                self.assertLess(recorded["wall_seconds"], 2)
                with self.assertRaisesRegex(RuntimeError, "did not finish"):
                    asyncio.run(runner.pump(0, game_seconds=2))
            finally:
                runner.status_log.close()

    def test_game_and_wall_durations_are_exclusive_and_finite(self):
        parser = headless.build_parser()
        cmd = ["host", "--relay", "ws://127.0.0.1:8000/relay", "--seats", "red",
               "--data", ".", "--runtime", "."]
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                parser.parse_args(cmd + ["--seconds", "60", "--game-seconds", "10"])
            for value in ("nan", "inf", "0", "-1"):
                with self.assertRaises(SystemExit):
                    headless.validate(parser.parse_args(cmd + ["--game-seconds", value]), parser)
        args = parser.parse_args(cmd + ["--game-seconds", "60"])
        headless.validate(args, parser)
        self.assertEqual(args.game_seconds, 60)
