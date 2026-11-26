from contextlib import redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from bots import run
from bots.match_storage import match_scratch
from bots.navigation_memory import NavigationMemory, parse_observation
from manager import config
from tests.test_navigation_memory import ARRIVE


class MatchStorageTests(unittest.TestCase):
    def test_fixed_prior_and_live_rules_use_engine_event_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            game, memory = root / "game", root / "memory"
            for name in ("resource", "episode"):
                (game / name).mkdir(parents=True)
            profile = list(run.load_profiles().values())[0]
            player = profile["name"]
            edge = ARRIVE.replace("name=Jan ", f"name={player} ")
            engine = Path(sys.executable)
            with engine.open("rb") as stream:
                build = hashlib.file_digest(stream, "sha256").hexdigest()
            ff = NavigationMemory(memory, profile["id"], build, "ff-guns")
            nf = NavigationMemory(memory, profile["id"], build, "nf-sabers")
            ff.observe("previous-game",1,[parse_observation(edge, player)])
            cfg = dict(config.DEFAULT, game_data=str(game), max_players=5, rank=8,
                       bots_force_enabled=True, bots_sabers_only=False)
            for fixed in (True, False):
                with self.subTest(fixed=fixed):
                    live = None if fixed else root/"live.cfg"
                    if live:
                        run.write_behavior(live,cfg)
                    def spawn(command, *,stdout, env, **kwargs):
                        path = Path(env["JK_BOT_BEHAVIOR_FILE"])
                        self.assertEqual(path.read_text(), "version=1\nsabers_only=0\nfists_peace=1\nforce_enabled=1\n")
                        lines = ["BOT_JOINED slot=1 net=17",edge]
                        if fixed:
                            prior = Path(env["ADJOIN_EDGE_MODEL"])
                            self.assertEqual(hashlib.sha256(prior.read_bytes()).hexdigest(),ff.snapshot()[1])
                            receipt = prior.parent.parent/"behavior.cfg"
                            self.assertNotEqual(path,receipt)
                            run.write_behavior(receipt, dict(cfg,bots_sabers_only=True))
                            self.assertIn("sabers_only=0", path.read_text())
                        else:
                            self.assertNotIn("ADJOIN_EDGE_MODEL",env)
                            self.assertEqual(path,live)
                            # Both rule transitions and all observations reach one log poll.
                            # At poll time the file is already back at FF/guns.
                            lines.extend([f"BOT_BEHAVIOR name={player} sabers_only=1 fists_peace=1 force_enabled=0",
                                          edge, "BOT_BEHAVIOR name=Other sabers_only=0 fists_peace=1 force_enabled=1",
                                          edge, f"BOT_BEHAVIOR name={player} sabers_only=0 fists_peace=1 force_enabled=1",
                                          edge])
                        stdout.write(("\n".join(lines)+"\n").encode())
                        stdout.flush()
                        return Mock(pid=99, poll=Mock(return_value=None))
                    with patch.dict(os.environ, {"DISPLAY":":99"}), patch.object(run.sys,"platform","linux"), \
                         patch.object(run,"memory_root",return_value=memory), patch.object(run,"stop_group"), \
                         patch.object(run.subprocess,"Popen",side_effect=spawn), redirect_stdout(io.StringIO()):
                        code,directory = run.launch(cfg,[profile],engine=engine,connect="127.0.0.1:3500",
                            runtime=root/"logs",seconds=.01,taunts=False,behavior_file=live)
                    self.assertEqual(code,0)
                    result=json.loads((directory/"session.json").read_text())
                    self.assertEqual(result["behavior_mode"],"fixed" if fixed else "live")
                    self.assertEqual(result["bots"][0]["navigation_observations"],1 if fixed else 4)
                    self.assertEqual(ff.snapshot()[2],2 if fixed else 4)
                    if fixed:
                        self.assertIsNone(nf.snapshot())
                    else:
                        self.assertEqual(nf.snapshot()[2], 2)

    def test_fresh_scratch_per_match_and_cleanup_on_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            scratch = base / "scratch"
            scratch.mkdir()
            keep = scratch / "existing"
            keep.write_text("keep")
            with patch.dict(os.environ, {"ADJOIN_MATCH_SCRATCH": str(scratch)}):
                with self.assertRaises(RuntimeError):
                    with match_scratch(None, (base / "owned",)) as first:
                        self.assertEqual(first.parent, scratch)
                        with match_scratch(None, (base / "owned",)) as second:
                            self.assertNotEqual(first, second)
                            if os.name == "posix":
                                self.assertEqual(second.stat().st_mode & 0o077, 0)
                        (first / "partial.gob").write_bytes(b"partial")
                        raise RuntimeError("simulated staging failure")
                self.assertFalse(first.exists())
                self.assertFalse(second.exists())
                self.assertEqual(keep.read_text(), "keep")

    def test_root_inside_inputs_rejected_before_staging(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / "data"
            scratch = data / "scratch"
            scratch.mkdir(parents=True)
            with self.assertRaises(ValueError), match_scratch(scratch, (data,)):
                self.fail("created a scratch directory inside the originals")
            self.assertEqual(list(scratch.iterdir()), [])

    def test_private_baseline_never_links_the_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "installed"
            source.mkdir()
            original = source / "map.gob"
            original.write_bytes(b"owned")
            run.stage_tree(source, root / "match")
            copy = root / "match/map.gob"
            self.assertFalse(copy.samefile(original))
            run.stage_tree(root / "match", root / "seat", private_source=True)
            with patch("bots.run.os.link", side_effect=OSError("unsupported")):
                run.stage_tree(root / "match", root / "fallback", private_source=True)
            self.assertEqual((root / "fallback/map.gob").read_bytes(), b"owned")
            self.assertFalse((root / "fallback/map.gob").samefile(copy))
            self.assertTrue((root / "seat/map.gob").samefile(copy))
            self.assertFalse((root / "seat/map.gob").samefile(original))
            (root / "seat/map.gob").write_bytes(b"test mutation")
            self.assertEqual(original.read_bytes(), b"owned")

    def test_multi_seat_launcher_copies_originals_once_and_retains_logs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scratch = root / "scratch"
            scratch.mkdir()
            game = root / "game"
            (game / "Resource").mkdir(parents=True)
            (game / "Episode").mkdir()
            original = game / "Resource/res1.gob"
            original.write_bytes(b"original")
            (game / "Episode/jk1mp.gob").write_bytes(b"episode")
            profiles = list(run.load_profiles().values())[:2]
            cfg = dict(config.DEFAULT, game_data=str(game), max_players=5)
            env = {"DISPLAY": ":99", "ADJOIN_MATCH_SCRATCH": str(root / "unused")}
            for fail in (False, True):
                with self.subTest(fail=fail):
                    seat_files = []
                    def spawn(command, *, cwd, stdout, **kwargs):
                        self.assertTrue(cwd.is_relative_to(scratch))
                        seat = cwd / "resource/res1.gob"
                        self.assertFalse(seat.samefile(original))
                        if seat_files:
                            self.assertTrue(seat.samefile(seat_files[0]))
                        seat_files.append(seat)
                        stdout.write(b"BOT_JOINED slot=1 net=17\n")
                        stdout.flush()
                        if fail and len(seat_files) == 2:
                            raise OSError("simulated second seat failure")
                        return Mock(pid=99, poll=Mock(return_value=None))
                    with patch.dict(os.environ, env), patch.object(run.sys, "platform", "linux"), \
                         patch.object(run, "memory_root", return_value=None), \
                         patch.object(run, "stop_group"), patch.object(run.subprocess, "Popen", side_effect=spawn), \
                         patch.object(run.shutil, "copy2", wraps=run.shutil.copy2) as copy_file, redirect_stdout(io.StringIO()):
                        code, directory = run.launch(cfg, profiles, engine=Path(sys.executable),
                            connect="127.0.0.1:3500", runtime=root / "logs", seconds=0.01,
                            taunts=False, scratch_root=scratch)
                    original_reads = [Path(call.args[0]) for call in copy_file.call_args_list
                                      if Path(call.args[0]).is_relative_to(game)]
                    self.assertCountEqual(original_reads, [original, game / "Episode/jk1mp.gob"])
                    self.assertEqual(code, int(fail))
                    receipt = json.loads((directory / "session.json").read_text())
                    self.assertEqual(receipt["result"], "failed" if fail else "duration_complete")
                    for row in receipt["bots"]:
                        seat_dir = Path(row["directory"])
                        self.assertEqual(seat_dir.parent, directory)
                        self.assertEqual((seat_dir / "client.log").read_text(), "BOT_JOINED slot=1 net=17\n")
                        self.assertTrue((seat_dir / "persona.tsv").is_file())
                        self.assertFalse((seat_dir / "resource").exists())
                        self.assertFalse(Path(row["engine_directory"]).exists())
                    self.assertEqual(list(scratch.iterdir()), [])
                    self.assertEqual(original.read_bytes(), b"original")
