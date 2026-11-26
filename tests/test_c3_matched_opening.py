import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.bot_development.c3_matched_opening import COG, build
from scripts.bot_development.controlled_opening import read_entries


class MatchedC3Fixture(unittest.TestCase):
    def test_refuses_unknown_episode_before_writing(self):
        with TemporaryDirectory() as directory:
            source = Path(directory) / "source.gob"
            output = Path(directory) / "fixture.gob"
            source.write_bytes(b"unknown episode")
            with self.assertRaisesRegex(ValueError, "stock JK1CTF"):
                build(source, output)
            self.assertFalse(output.exists())

    @unittest.skipUnless(os.environ.get("C3_EPISODE"), "Set C3_EPISODE to an owned stock JK1CTF.GOB")
    def test_reproduces_the_played_fixture_with_only_one_cog_changed(self):
        source = Path(os.environ["C3_EPISODE"])
        with TemporaryDirectory() as directory:
            output = Path(directory) / "JK1CTF.GOB"
            receipt = build(source, output)
            self.assertEqual(receipt["episode_sha256"], "fa880206acec5190429e1cad9df77326c21e372fecb0053df50f6e2adb6cfb32")
            stock, drill = read_entries(source), read_entries(output)
            self.assertEqual(stock.keys(), drill.keys())
            self.assertEqual([key for key in stock if stock[key] != drill[key]], [COG])
            with self.assertRaises(FileExistsError):
                build(source, output)
