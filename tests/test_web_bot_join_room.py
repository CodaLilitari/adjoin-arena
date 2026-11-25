import struct
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

from web_bots.join_room import ZONE_RELAY, relay_url, select_room, unsupported


class SelectedRoomTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.data = Path(directory.name)
        episode = self.data / "Episode"
        episode.mkdir()
        # A real GOB index containing one small level resource.
        level = b"fixture"
        archive = (b"GOB " + struct.pack("<II", 20, 12+len(level)) + level +
                   struct.pack("<III128s", 1, 12, len(level), b"jkl\\test.jkl"))
        (episode/"Practice.gob").write_bytes(archive)
        self.args = Namespace(data=self.data, room_id=82, seat="boba", relay=ZONE_RELAY, episode_gob=None)
        self.game = dict(id=82, name="Two rooms can share this", game="jk1", net=2,
                         locked=False, players=1, max=4, mod="", episode="Practice", map="test.jkl")

    def test_resolves_exact_identity_and_local_episode(self):
        result = select_room([{**self.game, "id":81}, self.game], self.args)
        self.assertEqual(result.room_id, 82)
        self.assertEqual(result.episode_file, self.data / "Episode" / "Practice.gob")
        with self.assertRaisesRegex(ValueError, "absent or ambiguous"):
            select_room([{**self.game, "id":81}], self.args)
        with self.assertRaisesRegex(ValueError, "absent or ambiguous"):
            select_room([self.game, self.game], self.args)

    def test_ineligible_and_unknown_assets(self):
        for change in (dict(locked=True),dict(players=4),dict(net=3),dict(game="mots"),
                       dict(mod="different"),dict(map="../test.jkl"),dict(episode="jk1mpdem")):
            with self.subTest(change=change):
                self.assertTrue(unsupported({**self.game, **change}))
        with self.assertRaisesRegex(ValueError, "advertised JKL"):
            select_room([{**self.game, "map":"absent.jkl"}], self.args)
        self.args.episode_gob = self.data / "Episode" / "wrong.gob"
        with self.assertRaisesRegex(ValueError, "episode name"):
            select_room([self.game], self.args)

    def test_relay_is_explicit(self):
        self.assertEqual(relay_url(ZONE_RELAY), ZONE_RELAY)
        loopback = "ws://127.0.0.1:5098/relay"
        self.assertEqual(relay_url(loopback), loopback)
        for url in (loopback+"?key=private", loopback+"/else", "ws://localhost:5432/relay",
                    "wss://user@jediknight.zone/relay"):
            with self.assertRaises(ValueError):
                relay_url(url)
