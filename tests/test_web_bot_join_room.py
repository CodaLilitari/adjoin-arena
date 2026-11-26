import struct
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

from web_bots.join_room import SelectedRoom, ZONE_RELAY, join_rules, listed_rank, relay_url, select_room, unsupported


class JoiningRulesTests(unittest.IsolatedAsyncioTestCase):
    async def test_bank_comes_from_selected_lobby_entry(self):
        from aiohttp import web
        from aiohttp.test_utils import TestServer

        entry = bytearray(240)
        entry[88:91] = b"jhs"
        entry[120:127] = b"jhs.jkl"
        queries = []
        async def relay(request):
            socket = web.WebSocketResponse()
            await socket.prepare(request)
            msg = await socket.receive_str()
            queries.append((msg, request.query.get("net"), request.query.get("pw")))
            await socket.send_str("list 12 1 "+entry.hex())
            return socket

        app = web.Application()
        app.router.add_get("/relay", relay)
        async with TestServer(app, host="127.0.0.1") as server:
            room = SelectedRoom(f"ws://127.0.0.1:{server.port}/relay", 12, "jhs", "jhs.jkl", "red", None)
            for rank, rules, saving in [(0,"nf-guns",True),(8,"ff-guns",True),(3,"ff-guns",False)]:
                struct.pack_into("<i",entry,236,rank)
                self.assertEqual(await join_rules(room, False),(rules,saving))
            entry[120] = ord("x")
            self.assertEqual(await join_rules(room, True),("ff-sabers",False))
            self.assertEqual(queries, [("list jk1","2","1")]*4)


class SelectedRoomTests(unittest.TestCase):
    def test_native_room_entry_identity_and_force_rank(self):
        room = SelectedRoom("ws://127.0.0.1:3421/relay", 12, "jhs", "jhs.jkl", "red", None)
        raw = bytearray(240)
        raw[88:91] = b"JHS"
        raw[120:127] = b"jhs.jkl"
        for rank in (0, 4, 8, 255):
            struct.pack_into("<i",raw,236,rank)
            result = listed_rank("list 12 1 "+raw.hex(), room)
            self.assertEqual(result,rank if rank <= 8 else None)
        self.assertIsNone(listed_rank("list 12 1 abc", room))
        raw[120] = ord("x")
        self.assertIsNone(listed_rank("list 12 1 "+raw.hex(), room))

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
