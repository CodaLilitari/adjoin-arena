"""Admission pins for ordinary native clients on operator-selected maps."""
import hashlib
from pathlib import Path
import struct
import tempfile
import unittest

from bots.run import custom_episode


class NativeCustomEpisode(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.data = Path(directory.name)
        (self.data / "episode").mkdir()
        self.cfg = dict(episode="FreshPractice", map="balcony.jkl", teams=False, game_flags=0)
        self.archive = self.data / "episode" / "FRESHPractice.GOB"

    def install(self, kind):
        resources = {"episode.jk": f'"Practice"\nTYPE {kind}\n'.encode(), "jkl\\balcony.jkl": b"test level"}
        payload, entries = bytearray(), bytearray()
        for name, data in resources.items():
            entries += struct.pack("<II128s", 12+len(payload), len(data), name.encode())
            payload += data
        self.archive.write_bytes(struct.pack("<4sII", b"GOB ",20,12+len(payload))+
                                 payload+struct.pack("<I",len(resources))+entries)

    def test_configured_peer_archive_and_actual_jkl_are_pinned(self):
        self.install(2)
        pins = custom_episode(self.cfg, self.data, "arena:3346")
        self.assertEqual(pins["ADJOIN_CUSTOM_ENDPOINT"], "arena:3346")
        self.assertEqual(pins["ADJOIN_CUSTOM_MODE"], "ffa")
        self.assertEqual(pins["ADJOIN_CUSTOM_GOB_SHA256"], hashlib.sha256(self.archive.read_bytes()).hexdigest())
        self.assertEqual(pins["ADJOIN_CUSTOM_MAP_SHA256"], hashlib.sha256(b"test level").hexdigest())
        with self.assertRaisesRegex(ValueError, "missing.jkl"):
            custom_episode(dict(self.cfg, map="missing.jkl"), self.data, "arena:3346")
        with self.assertRaisesRegex(ValueError, "team-skins"):
            custom_episode(dict(self.cfg, teams=True), self.data, "arena:3346")
        self.assertEqual(custom_episode(dict(self.cfg, teams=True, game_flags=256),
                                        self.data, "arena:3346")["ADJOIN_CUSTOM_MODE"], "tdm")

    def test_custom_ctf_and_stock(self):
        self.install(8)
        with self.assertRaisesRegex(ValueError, "Team game"):
            custom_episode(self.cfg, self.data, "arena:3346")
        self.assertEqual(custom_episode(dict(self.cfg, teams=True), self.data, "arena:3346")["ADJOIN_CUSTOM_MODE"], "ctf")
        self.assertEqual(custom_episode(dict(self.cfg, episode="JK1MP"), self.data, "arena:3346"), {})
        self.install(1)
        with self.assertRaisesRegex(ValueError, "multiplayer"):
            custom_episode(self.cfg, self.data, "arena:3346")

