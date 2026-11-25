"""Seat identity, physical opening assignment and sampled repeater ownership."""
import contextlib
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts.bot_development import controlled_opening as opening
from scripts.bot_development.legacy import native_force_observation as launcher


class SwappedStartTests(unittest.TestCase):
    def setUp(self):
        self.folder = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.bots = {"dark": {"joined": {"slot": 1, "net": 3}}, "light": {"joined": {"slot": 2, "net": 5}}}
        self.gate = {"owners": {k: dict(**v["joined"], release_time_s=0.2, unlock_time_s=0.2)
                               for k, v in self.bots.items()}}

    def write(self, swapped=False):
        for name, seat in self.bots.items():
            slot, net = seat["joined"]["slot"], seat["joined"]["net"]
            sector, pos = opening.STARTS[3-slot if swapped else slot]
            coords = " ".join(map(str, pos))
            self.path(name).write_text(
                f"OpenJKDF2: sithWorld_Load -> m10.jkl\nBOT_JOINED slot={slot} net={net}\n"
                f"ADJOIN_OPENING\n{slot}\n{sector}\n<{coords}>\n0\n0\nADJOIN_RIFLE_BASE\n0\n"
                f"ARENA_REPEATER_BASE\n{slot}\n0\n0.0\nGATE_UNLOCK_APPLIED\n{slot}\n0\n1\n1\n1\n0.2\n",
                encoding="ascii")

    def path(self, side):
        return self.folder / (side + ".log")

    def measure(self, *, swapped=False):
        openings = opening.qualify(self.folder, self.bots, swap_starts=swapped)
        return opening.qualify_repeater(self.folder, openings, self.gate)

    def test_swaps_only_two_mask_literals_with_identical_optional_instrumentation(self):
        for instrument in (False, True):
            normal = opening.opening_script(True, False, instrument)
            swapped = opening.opening_script(True, True, instrument)
            reversed_masks = normal.replace(b"0xFFFFFFFD", b"MASK_LOWER").replace(
                b"0xFFFFFBFF", b"0xFFFFFFFD").replace(b"MASK_LOWER", b"0xFFFFFBFF")
            self.assertEqual(reversed_masks, swapped)
            self.assertEqual(normal.count(b"0xFFFFFFFD"), 1)
            self.assertEqual(normal.count(b"0xFFFFFBFF"), 1)
            self.assertEqual(normal.count(b'Print("ARENA_REPEATER_CHANGE")'), int(instrument))
        self.assertEqual(opening.digest(opening.opening_script(True, False, False)),
                         "9091f7c115823b72e2633f8d9324d1d972a56dd47076f4ffa75841a5c10e256f")

    def test_physical_poses_and_owner_slots_must_both_match(self):
        self.write(swapped=True)
        self.assertEqual(self.measure(swapped=True)["dark"]["slot"], 1)
        with self.assertRaises(ValueError):
            self.measure()
        self.write()
        with self.assertRaises(ValueError):
            self.measure(swapped=True)
        # Renaming the logs and the alleged connection records cannot impersonate
        # a physical swap even if each file remains internally self-consistent.
        dark, light = (self.path(side).read_bytes() for side in ("dark", "light"))
        self.path("dark").write_bytes(light)
        self.path("light").write_bytes(dark)
        self.bots["dark"], self.bots["light"] = self.bots["light"], self.bots["dark"]
        with self.assertRaises(ValueError):
            self.measure(swapped=True)

    def test_first_life_gain_excludes_respawns_and_gains_on_later_lives(self):
        self.write()
        first_gain = "ARENA_REPEATER_CHANGE\n2\n0\n1\n1.3\n"
        with self.path("light").open("a") as out:
            out.write(first_gain)
        with self.path("dark").open("a") as out:
            out.write("ADJOIN_RESPAWN\n1\n18\n<2 1 0>\n0\nADJOIN_RIFLE_BASE\n0\n"
                      "ARENA_REPEATER_BASE\n1\n0\n2.0\nBOT_RESPAWN name=bot\n"
                      "ARENA_REPEATER_CHANGE\n1\n0\n1\n2.5\n")
        result = self.measure()
        self.assertEqual(result["light"]["first_life_gain_after_release_s"], 1.1)
        self.assertIsNone(result["dark"]["first_life_gain_after_release_s"])
        self.assertEqual(result["dark"]["events"][-1]["life_ordinal"], 2)

    def test_missing_ambiguous_or_pre_release_repeater_readbacks_fail(self):
        for before, after in (
            ("ARENA_REPEATER_BASE\n1\n0\n0.0\n", ""),
            ("ARENA_REPEATER_BASE\n1\n0", "ARENA_REPEATER_BASE\n2\n0"),
            ("ARENA_REPEATER_BASE\n1\n0", "ARENA_REPEATER_BASE\n1\n1"),
            ("GATE_UNLOCK_APPLIED", "ARENA_REPEATER_CHANGE\n1\n0\n1\n0.5\nGATE_UNLOCK_APPLIED"),
            ("0.2\n", "0.2\nARENA_REPEATER_CHANGE\n1\n0\n1\n0.05\n"),
            ("0.2\n", "0.2\nARENA_REPEATER_CHANGE\n1\n1\n0\n1.5\n"),
            ("0.2\n", "0.2\nARENA_REPEATER_CHANGE\n2\n0\n1\n1.5\n"),
        ):
            with self.subTest(before=before, after=after):
                self.write()
                path = self.path("dark")
                self.assertEqual(path.read_text().count(before), 1)
                path.write_text(path.read_text().replace(before, after))
                with self.assertRaises(ValueError):
                    self.measure()

    def test_options_require_ready_gate_through_the_cli_and_builder(self):
        for option in ("--swap-starts", "--observe-repeater"):
            argv = ["launcher", "--repo", ".", "--data", ".", "--output", ".", "--arena-baseline",
                    "--map", "m10.jkl", "--controlled-opening", option]
            with patch.object(sys, "argv", argv), contextlib.redirect_stderr(io.StringIO()), \
                 self.assertRaises(SystemExit) as failure:
                launcher.main()
            self.assertEqual(failure.exception.code, 2)
            with self.assertRaises(ValueError):
                opening.opening_script(False, option == "--swap-starts", option == "--observe-repeater")
