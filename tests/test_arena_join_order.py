"""Alternate the native join order while keeping Force profiles and starts independently bound."""
from contextlib import redirect_stderr
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts.bot_development import controlled_opening as opening
from scripts.bot_development.legacy import native_force_observation as launcher


class JoinOrderTests(unittest.TestCase):
    def setUp(self):
        self.folder = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def write_logs(self, *, jan_first, swapped=False):
        self.bots = {}
        self.gate = {"owners": {}}
        first = "light" if jan_first else "dark"
        for side in ("light", "dark"):
            slot = 1 if side == first else 2
            net = 3 if slot == 1 else 5
            self.bots[side] = {"joined": {"slot": slot, "net": net}}
            self.gate["owners"][side] = dict(slot=slot, net=net, release_time_s=.3, unlock_time_s=.3)
            sector, pos = opening.STARTS[3-slot if swapped else slot]
            coords = " ".join(map(str, pos))
            name = "Bot_JanOrs" if side == "light" else "Bot_BobaFett"
            (self.folder / (side + ".log")).write_text(
                f"BOT_DISCOVER name={name} endpoint=127.0.0.1:6543 skin=x\n"
                f"BOT_LOADOUT rank=8 side={side} style=competitive spent=24 remaining=0\n"
                f"OpenJKDF2: sithWorld_Load -> m10.jkl\nBOT_JOINED slot={slot} net={net}\n"
                f"ADJOIN_OPENING\n{slot}\n{sector}\n<{coords}>\n0\n0\nADJOIN_RIFLE_BASE\n0\n"
                f"ARENA_REPEATER_BASE\n{slot}\n0\n0.0\nGATE_UNLOCK_APPLIED\n{slot}\n"
                f"ARENA_REPEATER_CHANGE\n{slot}\n0\n1\n1.5\n", encoding="ascii")

    def test_boot_order_changes_while_the_environment_indices_and_force_sides_hold(self):
        default = ((0, ("dark", "boba_fett")), (1, ("light", "jan_ors")))
        self.assertEqual(launcher.seat_schedule(False), default)
        self.assertEqual(launcher.seat_schedule(True), (default[1], default[0]))

    def test_both_orders_and_layouts_are_independent(self):
        for jan_first in (False, True):
            for swapped in (False, True):
                with self.subTest(jan_first=jan_first, swapped=swapped):
                    self.write_logs(jan_first=jan_first, swapped=swapped)
                    owners = opening.qualify(self.folder, self.bots, jan_first=jan_first, swap_starts=swapped)
                    actual = opening.qualify_repeater(self.folder, owners, self.gate, jan_first=jan_first)
                    self.assertEqual(actual["light"]["slot"], 1 if jan_first else 2)
                    self.assertEqual(actual["dark"]["first_life_gain_after_release_s"], 1.2)
                    with self.assertRaises(ValueError):
                        opening.qualify(self.folder, self.bots, jan_first=not jan_first, swap_starts=swapped)
                    with self.assertRaises(ValueError):
                        opening.qualify_repeater(self.folder, owners, self.gate, jan_first=not jan_first)

    def test_relabeling_files_and_connections_cannot_fake_reversed_order(self):
        self.write_logs(jan_first=False)
        dark, light = (self.folder / (side + ".log") for side in ("dark", "light"))
        dark_contents, light_contents = dark.read_bytes(), light.read_bytes()
        dark.write_bytes(light_contents)
        light.write_bytes(dark_contents)
        self.bots["dark"], self.bots["light"] = self.bots["light"], self.bots["dark"]
        with self.assertRaisesRegex(ValueError, "profile"):
            opening.qualify(self.folder, self.bots, jan_first=True)

    def test_jan_first_requires_an_actual_native_profile_and_matching_force(self):
        self.write_logs(jan_first=True)
        log = self.folder / "light.log"
        initial = log.read_text()
        for bad in (initial.replace("side=light", "side=dark"), initial.replace("BOT_DISCOVER ", "SKIPPED "),
                    initial.replace("name=Bot_JanOrs", "name=Bot_BobaFett")):
            with self.subTest(bad=bad):
                log.write_text(bad)
                with self.assertRaisesRegex(ValueError, "profile"):
                    opening.qualify(self.folder, self.bots, jan_first=True)

    def test_cli_rejects_jan_first_without_the_ready_gate(self):
        flags = ["launcher", "--repo", ".", "--data", ".", "--output", ".", "--jan-first"]
        with patch.object(sys, "argv", flags), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as invalid:
            launcher.main()
        self.assertEqual(invalid.exception.code, 2)
