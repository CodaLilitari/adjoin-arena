import contextlib
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts.bot_development import ready_gate
from scripts.bot_development.legacy import native_force_observation as launcher


def marker(mode, phase):
    suffix = ("game_ms=100 policy_s=0.000000 actor_mask=2359296 gravity=0 collision=0" if phase == "held"
              else f"game_ms=250 policy_s={0 if mode == 'on' else .15:.6f} actor_mask=0 gravity=1 collision=1")
    return f"BOT_PLANNER_GATE name=Bot_JanOrs mode={mode} phase={phase} slot=1 {suffix}"


PLAN = "BOT_GEAR name=Bot_JanOrs t=0.03 event=plan item=29 guid=29 signature=30 pack=0 anchor=30 direct=1"


class PlannerEvidenceTests(unittest.TestCase):
    def verify(self, mode, edits=(), plan_after=True):
        lines = ["BOT_DISCOVER name=Bot_JanOrs endpoint=127.0.0.1:22", "GATE_SCRIPT_LOADED", "GATE_HELD",
                 marker(mode, "held"), "GATE_LOCAL_RELEASE", "GATE_UNLOCK_APPLIED", marker(mode, "released")]
        lines.insert(len(lines) if plan_after else 4, PLAN)
        for old, new in edits:
            lines[lines.index(old):lines.index(old)+1] = new
        log = object.__new__(ready_gate.Log)
        log.lines = lines
        log.records = {s: [ready_gate.Event(i, ())] for i, s in enumerate(lines) if s.startswith("GATE_")}
        return ready_gate.planner_evidence(log, {"slot": 1}, mode)

    def test_positive_native_edges_and_cold_or_advancing_policy(self):
        for mode, after in (("on", True), ("off", False)):
            result = self.verify(mode, plan_after=after)
            self.assertEqual(result["first_gear_plan_after_release"], after)
            self.assertEqual(result["first_gear_plan"]["item"], 29)
            self.assertEqual(result["held"]["actor_mask"], 2359296)
        self.assertIsNone(self.verify("on", [(PLAN, [])])["first_gear_plan_after_release"])

    def test_require_matching_name_slot_mode_pose_and_progress(self):
        held, released = marker("on", "held"), marker("on", "released")
        for old, new in [(held, []), (released, [released, released]), (held, [held.replace("slot=1", "slot=2")]),
                         (held, [held.replace("JanOrs", "BobaFett")]), (held, [held.replace("on ", "off ")]),
                         (held, [held.replace("gravity=0", "gravity=1")]),
                         (released, [released.replace("0.000000", "0.031000")]),
                         (released, [released.replace("250", "99")])]:
            with self.subTest(old=old, new=new), self.assertRaises(ValueError):
                self.verify("on", [(old, new)])
        with self.assertRaisesRegex(ValueError, "before native release"):
            self.verify("on", plan_after=False)
        released = marker("off", "released")
        with self.assertRaisesRegex(ValueError, "did not advance"):
            self.verify("off", [(released, [released.replace("0.150000", "0.000000")])])

    def test_options_require_private_instrumented_fixture(self):
        base = ["observe", "--repo", "r", "--data", "d", "--output", "o", "--map", "m10.jkl",
                "--arena-baseline", "--ready-gate"]
        for extra in (["--planner-client", "bot"], ["--planner-quarantine", "on"],
                      ["--planner-client", "bot", "--planner-quarantine", "off"]):
            with self.subTest(extra=extra), patch.object(sys, "argv", base + extra), \
                    contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                launcher.main()
            self.assertEqual(error.exception.code, 2)


class PlannerBuildTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.object(launcher, "check"))

    def put(self, relative, content):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def test_private_manifest_binary_library_patch_and_published_inputs_are_bound(self):
        h = lambda value: hashlib.sha256(value).hexdigest()
        bot = self.put("external/jk-bot-client", b"research")
        self.put("external/" + launcher.GNS, b"lib")
        archive = "native/bot-relink-linux-x86_64.tar.gz"
        overlay = "native/planner-go.patch"
        self.put(archive, b"relink")
        self.put(overlay, b"overlay")
        packaged = {"base_commit": "base", "files": {archive: {"sha256": h(b"relink")}}}
        side_lib = str(Path(launcher.BOT).parent / launcher.GNS)
        host_lib = str(Path(launcher.SERVER).parent / launcher.GNS)
        hashes = {launcher.BOT: h(b"stock"), launcher.PATCH: h(b"stockpatch"), side_lib: h(b"lib"),
                  launcher.SERVER: h(b"server"), host_lib: h(b"hostlib")}
        host_manifest = {"files": {key: {"sha256": hashes[key]} for key in (host_lib, launcher.SERVER)}}
        self.put("native/BUILD.json", json.dumps(host_manifest).encode())
        build = dict(source_commit="base", patch=overlay, patch_sha256=h(b"overlay"), binary_sha256=h(b"research"),
                     base_binary_sha256=h(b"stock"), base_patch_sha256=h(b"stockpatch"), gns_sha256=h(b"lib"),
                     relink_archive_sha256=h(b"relink"), toolchain="test compiler")
        data = json.dumps(build).encode()
        self.put("native/planner-go-build.json", data)
        self.put("external/planner-build.json", data)
        self.assertEqual(launcher.research_client(self.root, bot, packaged, hashes), (bot, build))
        self.assertEqual(hashes["research/jk-bot-client"], h(b"research"))
        for path, original in [("external/planner-build.json", data), ("external/jk-bot-client", b"research"),
                               ("external/" + launcher.GNS, b"lib"), (overlay, b"overlay"), (archive, b"relink")]:
            self.put(path, b"changed")
            with self.subTest(path=path), self.assertRaises(launcher.Failure):
                launcher.research_client(self.root, bot, packaged, hashes)
            self.put(path, original)

    def test_live_maps_must_identify_the_expected_library_and_executable(self):
        engine = self.put("runtime/jk-bot-client", b"research")
        lib = self.put("runtime/" + launcher.GNS, b"lib")
        exe = self.put("process/exe", b"research")
        template = "7000-8000 r-xp 0000 01:02 {} /engine/" + launcher.GNS
        self.enterContext(patch.object(launcher.os, "major", return_value=1, create=True))
        self.enterContext(patch.object(launcher.os, "minor", return_value=2, create=True))
        self.put("process/maps", template.format(lib.stat().st_ino).encode())
        expected = launcher.digest(engine), launcher.digest(lib)
        self.assertEqual(launcher.loaded_images(exe.parent, engine, *expected)["executable_sha256"], expected[0])
        self.put("process/maps", template.format(lib.stat().st_ino + 1).encode())
        with self.assertRaises(launcher.Failure):
            launcher.loaded_images(exe.parent, engine, *expected)
