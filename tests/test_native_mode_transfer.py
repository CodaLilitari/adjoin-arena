import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from scripts.bot_development.legacy import native_mode_transfer as transfer


class NativeModeTransferTests(unittest.TestCase):
    def test_route_choice_is_bound_to_geometry_and_requires_same_life_arrivals_for_an_exit(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            source = root / "route"
            source.write_text("RED_ROUTE_HINT_V1 " + "c"*64 + " 2\n5 184 1 2 3\n7 -1 1 3 4\n")
            model = SimpleNamespace(mode="ffa", weapons="guns", force="on", route_hint=source,
                route_hint_sha256=hashlib.sha256(source.read_bytes()).hexdigest(), route_hint_scope="ffa/guns/force")
            content = {"map_sha256": "c"*64}
            cfg = transfer.stage_route_hint(model, content, root/"selected")
            path = root/"side.log"
            common = f" pid=7 map_sha={cfg['map_sha256']} hint_sha={cfg['sha256']} life=1 pos=0,0,0 fwd=1 slide=0"
            events = ["phase=load status=ready seq=0 sector=5 fixture=184",
                      "phase=start status=ready seq=0 sector=5 fixture=184",
                      "phase=step status=applied seq=0 sector=5 fixture=184",
                      "phase=arrive status=reached seq=0 sector=5 fixture=184",
                      "phase=exit status=reached seq=1 sector=7 fixture=-1"]
            logged = ["BOT_ROUTE_HINT " + event + common + "\n" for event in events]
            path.write_text("".join(logged))
            result = transfer.route_observations(path, cfg, 7)
            self.assertEqual(result["lives"]["1"]["exits"][0]["sector"], 7)
            path.write_text("".join(logged[:-1]) + logged[-1].replace("life=1", "life=2"))
            with self.assertRaisesRegex(ValueError, "same-life"):
                transfer.route_observations(path, cfg, 7)
            model.route_hint_scope = "ffa/guns/noforce"
            with self.assertRaisesRegex(ValueError, "ruleset"):
                transfer.stage_route_hint(model, content, root/"unselected")

    def test_platform_position_proof_uses_planar_distance_from_the_same_life(self):
        with TemporaryDirectory() as d:
            path = Path(d) / "owner.log"
            path.write_text("BOT_RED_FIRST life=1\n"
                            "BOT_PLATFORM_SUPPORT sector=5 fixture=landpad pos=1,2,3\n"
                            "BOT_STATUS health=100 pos=1,2,5 sector=5\n"
                            "BOT_STATUS health=75 pos=4,6,2 sector=7\n"
                            "BOT_RED_STATE life=2\n"
                            "BOT_STATUS health=100 pos=80,90,0 sector=115\n")
            evidence = transfer.platform_observations(path)["sampled_per_life_and_fixture"][0]
            self.assertEqual(evidence["max_xy_displacement"], 5)
            self.assertEqual(evidence["post_marker_positions"], 2)
            self.assertTrue(evidence["reached_another_sector"])

    def test_custom_join_and_vfs_pins_precede_control_on_each_process(self):
        content = {"episode": "CUSTOM", "map": "arena.jkl", "episode_sha256": "a"*64, "map_sha256": "b"*64}
        self.assertEqual(transfer.custom_environment(content, "ffa")["ADJOIN_CUSTOM_MAP_SHA256"], "b"*64)
        suffix = f" status=accepted episode=CUSTOM map=arena.jkl gob_sha={'a'*64} map_sha={'b'*64} mode=ffa pid=31\n"
        rows = ["BOT_RED_CUSTOM phase=admission" + suffix, "BOT_RED_CUSTOM phase=world" + suffix,
                "BOT_RED_FIRST name=test\n"]
        with TemporaryDirectory() as d:
            path = Path(d) / "owner.log"
            path.write_text("".join(rows))
            self.assertEqual(transfer.verify_custom_admission(path, content, "ffa", 31)["world_line"], 2)
            with self.assertRaises(ValueError):
                transfer.verify_custom_admission(path, content, "ffa", 32)
            path.write_text("".join([rows[0], rows[2], rows[1]]))
            with self.assertRaises(ValueError):
                transfer.verify_custom_admission(path, content, "ffa", 31)

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
