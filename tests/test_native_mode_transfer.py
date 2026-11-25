import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from scripts.bot_development.legacy import native_mode_transfer as transfer


class NativeModeTransferTests(unittest.TestCase):
    def test_declared_and_hashed_custom_level_is_staged_privately(self):
        with TemporaryDirectory() as directory:
            base=Path(directory);target=base/"game";(target/"episode").mkdir(parents=True)
            jkl=b"fixture geometry"
            seq=b'"Example"\nTYPE 2\nSEQ 1\n0: 0 1 LEVEL test.jkl 0 0 0 -1\n'
            gob=base/"PRIVATE.GOB";gob.write_bytes(jkl+seq)
            sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
            args=SimpleNamespace(episode_file=gob,map="test.jkl",episode_sha256=sha(gob),
                                 map_sha256=hashlib.sha256(jkl).hexdigest(),mode="ffa")
            entries=[{"name":"jkl/test.jkl","offset":0,"size":len(jkl)},
                     {"name":"episode.jk","offset":len(jkl),"size":len(seq)}]
            catalog=lambda _: {"episodes":[{"episode":"private","type":2,"title":"Example","maps":["test.jkl"]}]}
            dest,content=transfer.stage_episode(args,target,lambda _:entries,catalog,sha)
            self.assertEqual(dest.read_bytes(),gob.read_bytes())
            self.assertEqual(content["map_sha256"],args.map_sha256)
            args.mode="ctf"
            with self.assertRaisesRegex(ValueError,"wrong_episode_for_rules"):
                transfer.stage_episode(args,target,lambda _:entries,catalog,sha)
            args.mode="ffa";args.map_sha256="0"*64
            with self.assertRaisesRegex(ValueError,"manifest_mismatch"):
                transfer.stage_episode(args,target,lambda _:entries,catalog,sha)

    def test_experimental_candidate_on_wrong_map_or_rules_is_rejected(self):
        with TemporaryDirectory() as d:
            path=Path(d)/"weights";path.write_bytes(b"frozen")
            h=hashlib.sha256(path.read_bytes()).hexdigest(); m="d"*64
            a=SimpleNamespace(mode="tdm",weapons="guns",force="off",policy_weights=path,
                              trial_scope="tdm/guns/noforce",trial_map_sha256=m,trial_weights_sha256=h)
            self.assertEqual(transfer.selection(a,m)["reason"],"explicit_experimental_candidate")
            with self.assertRaisesRegex(ValueError,"trial_scope"):
                transfer.selection(a,"9"*64)
            a.mode="ctf";a.trial_scope="ctf/guns/noforce"
            with self.assertRaisesRegex(ValueError,"trial_scope"):
                transfer.selection(a,m)
