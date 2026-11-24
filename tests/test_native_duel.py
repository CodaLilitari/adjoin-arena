import json
import tempfile
import unittest
from pathlib import Path

from scripts.bot_development.analysis import native_duel as duel


NAV = "BOT_NAV nodes=10 map=m10.jkl name=Pilot item_nodes=1"
STATUS = ("BOT_STATUS name=Pilot t=10.0 sector=58 pos=1.0,2.0,3.0 health=100 "
          "weapon=9 target=-1 goal=3 path=1/2 kills=0 deaths=0 following=1")
PLAN = "BOT_GEAR name=Pilot t=2.0 event=plan item=29 pack=0"
CLEAR = "BOT_GEAR name=Pilot t=2.1 event=clear item=29 reason=state-or-contact"
FIRE = "BOT_FIRE_INPUT name=Pilot t=3.0 weapon=9 alternate=0"
STATE = "BOT_FORCE_STATE name=Pilot t=1.00 health=100 shields=100"


class DuelEvidenceTests(unittest.TestCase):
    def seat(self, *lines):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder) / "pilot.log"
            p.write_text("\n".join(lines) + "\n")
            return duel.read_seat(p, "Pilot")

    def test_rifle_plan_clear_and_fire_remain_distinct_observations(self):
        seat = self.seat(NAV, STATE, PLAN, CLEAR, FIRE, STATUS)
        self.assertEqual(seat["first_rifle_plan"]["t"], 2)
        self.assertEqual(seat["rifle_fire_input_reports"], 1)
        self.assertEqual(seat["first_rifle_selected_status"]["t"], 10)
        self.assertEqual(seat["first_gear_plan"]["item"], 29)

    def test_clear_alone_and_other_weapon_cannot_establish_rifle_evidence(self):
        seat = self.seat(NAV, STATE, CLEAR, FIRE.replace("weapon=9", "weapon=2"),
                         STATUS.replace("weapon=9", "weapon=2"))
        self.assertIsNone(seat["first_rifle_plan"])
        self.assertIsNone(seat["first_rifle_selected_status"])
        self.assertEqual(seat["rifle_fire_input_reports"], 0)

    def test_compares_position_and_sector_at_printed_samples(self):
        first = self.seat(NAV, STATE, PLAN, STATUS)
        repeat = self.seat(NAV, STATE, PLAN.replace("t=2.0","t=3.1"),
                           STATUS.replace("sector=58", "sector=10"))
        evidence = duel.compare_seat(first, repeat)
        self.assertEqual(evidence["first_status_difference"]["fields"], ["sector"])
        self.assertEqual(evidence["first_gear_items"], [29, 29])

    def test_does_not_accredit_a_different_map_seat_or_incomplete_log(self):
        for rows in [(NAV.replace("m10.jkl", "m2.jkl"), STATE, STATUS),
                     (NAV, STATE, STATUS.replace("Pilot", "Other")),
                     (NAV, STATE), (NAV, STATUS)]:
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                self.seat(*rows)

    def test_damage_sampling_resets_across_respawn_and_includes_shields(self):
        seat = self.seat(NAV, STATE, STATE.replace("t=1.00","t=2.00").replace("shields=100","shields=80"),
                         "BOT_RESPAWN name=Pilot health=100",
                         STATE.replace("t=1.00","t=3.00").replace("health=100","health=50"), STATUS)
        self.assertEqual(seat["resource_decrease_intervals"], 1)
        self.assertEqual(seat["respawn_reports"], 1)

    def test_restart_and_nonfinite_values_are_rejected(self):
        for rows in [(NAV, STATE, STATUS, STATUS), (NAV, STATE, STATUS.replace("1.0,2", "nan,2"))]:
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                self.seat(*rows)


    def make_run(self, root, port):
        root.mkdir()
        log = lambda name, text: (root / name).write_text(text + "\n")
        names = ["Pilot", "Wing"]
        log("server.log", "\n".join(n + " has joined the game" for n in names))
        for i, (side, name) in enumerate(zip(duel.SIDES, names), 1):
            log(side + ".log", f"BOT_JOINED slot={i} net={2*i+1}\n" + "\n".join((NAV, STATE, STATUS)).replace("Pilot", name))
        r = dict(kind="adjoin-arena-native-duel", network_interfaces=["lo"], pacing="normal engine wall-clock",
                 status="live_join_and_loadout_verified", sha256={"jkl/m10.jkl":duel.MAP_HASH, "jk1mp.gob":duel.EPISODE_HASH, duel.HOST:"f"*64},
                 server_registry=dict(portNum=port, serverMapJkl="m10.jkl", bIsDedicated=True),
                 log_sha256={n:duel.sha(root / n) for n in ("server.log", "dark.log", "light.log")},
                 bot_options={}, requested_match_seconds=10, dedicated_server_owned_udp_port=True,
                 launcher_sha256="a"*64, launcher_input_sha256={"bots/run.py":"b"*64},
                 bots={s:{"argv":["-botName",n,"-botConnect",f"127.0.0.1:{port}"],
                          "joined":{"slot":i,"net":2*i+1}}
                       for i,(s,n) in enumerate(zip(duel.SIDES,names),1)})
        (root / "receipt.json").write_text(json.dumps(r))

    def test_verified_run_inputs_and_changed_log(self):
        with tempfile.TemporaryDirectory() as folder:
            a, b = (Path(folder) / n for n in ("a", "b"))
            self.make_run(a, 1000)
            self.make_run(b, 2000)
            result = duel.compare_runs(a,b)
            self.assertEqual(result["runs"][0]["host_console_joins"], ["Pilot", "Wing"])
            with (b / "light.log").open("a") as f:
                f.write("tampered\n")
            with self.assertRaisesRegex(ValueError, "hash"):
                duel.compare_runs(a,b)

    def test_refuses_unverified_arena_and_changed_config(self):
        with tempfile.TemporaryDirectory() as folder:
            a, b = (Path(folder) / n for n in ("a", "b"))
            self.make_run(a, 1000)
            self.make_run(b, 2000)
            p = b / "receipt.json"
            r = json.loads(p.read_text())
            r["server_registry"]["maxRank"] = 5
            p.write_text(json.dumps(r))
            with self.assertRaisesRegex(ValueError, "settings"):
                duel.compare_runs(a,b)
            r["network_interfaces"] = ["lo","eth0"]
            p.write_text(json.dumps(r))
            with self.assertRaisesRegex(ValueError, "loopback"):
                duel.read_run(b)

    def test_host_roster_can_complete_buffered_console_with_verified_video(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "a"
            self.make_run(root, 1000)
            server = root / "server.log"
            server.write_text("Pilot has joined the game\n")
            directory = root / "spectator"
            directory.mkdir()
            movie = directory / "native-follow.mp4"
            movie.write_bytes(b"fixture")
            camera = directory / "observer-receipt.json"
            camera.write_text(json.dumps(dict(status="recorded", match=dict(map="m10.jkl",engine_sha256="f"*64),
                       joined_roster=[dict(name="Pilot",slot=1,peer_id=3),dict(name="Wing",slot=2,peer_id=5)],
                       followed=dict(name="Pilot", slot=1,peer_id=3),
                       captured=[dict(pose={"position":[1,2,3],"sector":58},received_monotonic=1+i*.2)
                                 for i in range(5)],
                       video=dict(sha256=duel.sha(movie), decoded_fully=True, record="fixture",
                                  stream=dict(nb_frames="5",duration="1.0")))))
            p = root / "receipt.json"
            r = json.loads(p.read_text())
            r["log_sha256"]["server.log"] = duel.sha(server)
            r["observer_status"]="recorded"
            r["observer_receipt_sha256"]=duel.sha(camera)
            p.write_text(json.dumps(r))
            report, _ = duel.read_run(root)
            self.assertEqual(report["host_console_joins"], ["Pilot"])
            self.assertEqual(report["host_roster"], ["Pilot", "Wing"])
            self.assertEqual(report["video"]["poses_in_rifle_sector"], 5)
            stationary = json.loads(camera.read_text())
            stationary["camera"] = "rifle-overlook"
            stationary.pop("followed")
            stationary["overlook"] = {"settled_pose":{"sector":41}}
            for frame in stationary["captured"]:
                frame["pose"]["sector"] = 41
            camera.write_text(json.dumps(stationary))
            r["observer_receipt_sha256"] = duel.sha(camera)
            p.write_text(json.dumps(r))
            movie = movie.rename(directory / "native-rifle-overlook.mp4")
            report, _ = duel.read_run(root)
            self.assertEqual(report["video"]["station_sector"], 41)
            self.assertNotIn("followed",report["video"])
            movie.write_bytes(b"unexpected")
            with self.assertRaisesRegex(ValueError, "video"):
                duel.read_run(root)

    def test_binds_endpoint_acknowledgement_and_episode(self):
        with tempfile.TemporaryDirectory() as folder:
            for i, error in enumerate(("endpoint", "acknowledgement", "stock")):
                with self.subTest(error=error), self.assertRaisesRegex(ValueError, error):
                    root = Path(folder) / str(i)
                    self.make_run(root, 1000)
                    p = root / "receipt.json"
                    r = json.loads(p.read_text())
                    if error == "endpoint":
                        r["bots"]["light"]["argv"][-1] = "127.0.0.1:9999"
                    elif error == "acknowledgement":
                        log = root / "light.log"
                        log.write_text(log.read_text().replace("BOT_JOINED slot=2 net=5", ""))
                        r["log_sha256"]["light.log"] = duel.sha(log)
                    else:
                        r["sha256"]["jk1mp.gob"] = "0"*64
                    p.write_text(json.dumps(r))
                    duel.read_run(root)
