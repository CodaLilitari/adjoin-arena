import contextlib
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from web_bots import headless


class PrivatePracticeClock(unittest.TestCase):
    def test_pace_memory_is_partitioned_for_both_host_and_joiner(self):
        from web_bots import serve
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in (*serve.ASSETS, "openjkdf2.js", "openjkdf2.wasm"):
                file = root / name
                file.parent.mkdir(exist_ok=True, parents=True)
                file.write_bytes(b"x")
            seat = SimpleNamespace(seat="lily", episode_file=None)
            for role in ("hosted", "external"):
                for pace, base, suffix in ((1, str(root/"nav"), "practice-1x"),
                                           (2, str(root/"nav"), "practice-2x"), (4, str(root/"nav"), "practice-4x"),
                                           (None, str(root/"nav"), ""), (2, "off", None)):
                    with patch.dict(os.environ, {"ADJOIN_NAV_MEMORY": base}):
                        host = serve.Host(root, root, root/f"{role}-{pace}-{suffix}", "Test", None, False,
                                          taunts=False, practice_rate=pace, **{role:seat})
                        try:
                            self.assertEqual(host.nav_root, root/"nav"/suffix if suffix is not None else None)
                            self.assertEqual(bool(host.nav_memories), suffix is not None)
                        finally:
                            host.close()

    def test_launcher_scope_and_asset_receipt(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            files = {name: sha256(name.encode()).hexdigest() for name in ("openjkdf2.wasm", "openjkdf2.js")}
            for name in files:
                (path/name).write_bytes(name.encode())
            (path/"practice-clock.json").write_text(json.dumps({"files": files}))
            parser = headless.build_parser()
            args = parser.parse_args(["host", "--seats", "red", "--room-name", "Practice", "--data", temp,
                                      "--runtime", temp, "--relay", "ws://127.0.0.1:1/relay", "--practice-rate", "2",
                                      "--engine-dir", temp])
            headless.validate(args, parser)
            with contextlib.redirect_stderr(io.StringIO()):
                args.practice_rate = 4
                with self.assertRaises(SystemExit):
                    headless.validate(args, parser)
                (path/"practice-clock.json").write_text(json.dumps({"files": files, "supported_rates":[1, 2, 4]}))
                headless.validate(args, parser)
                args.public_room = True
                with self.assertRaises(SystemExit):
                    headless.validate(args, parser)
                args.public_room = False
                args.relay = headless.ZONE_RELAY
                with self.assertRaises(SystemExit):
                    headless.validate(args, parser)
                args.relay = "ws://127.0.0.1:1/relay"
                (path/"openjkdf2.wasm").write_bytes(b"changed")
                with self.assertRaises(SystemExit):
                    headless.validate(args, parser)
                args.practice_rate = None
                headless.validate(args, parser)

    @unittest.skipUnless(shutil.which("clang") or shutil.which("cc"), "C compiler unavailable")
    def test_each_outer_step_preserves_control_and_physics_dt(self):
        source = Path(__file__).resolve().parents[1]/"web_bots/candidate/practice_clock.c"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root/"emscripten.h").write_text(
                "#define EM_JS(ret, name, args, ...) ret name args\ndouble emscripten_get_now(void);\n")
            main = root/"driver.c"
            main.write_text(r"""
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
int __wrap_sithUpdate(void);
void __wrap_sithTime_Advance(void), __wrap_jkBot_Tick(float), __wrap_sithThing_Update(float, int);
float sithTime_g_frameTimeFlex, sithTime_g_fps;
uint32_t sithTime_g_msecGameTime;
static int rate, phys, policy, updates;
static double wall;
double emscripten_get_now(void) { return wall; }
int requested_rate(void) { return rate; }
void __real_sithTime_Advance(void) { sithTime_g_msecGameTime += 17; }
void sithTime_SetFrameTime(int ms) { sithTime_g_msecGameTime += ms; }
void __real_jkBot_Tick(float seconds) { ++policy; }
void __real_sithThing_Update(float seconds, int ms) { ++phys; }
int __real_sithUpdate(void) {
    __wrap_sithTime_Advance();
    __wrap_jkBot_Tick(sithTime_g_frameTimeFlex);
    for (int i=0; i<5; ++i) __wrap_sithThing_Update(1.0f/150, 7);
    ++updates; return 0;
}
int main(int argc, char **argv) {
    rate = atoi(argv[1]);
    for (int i=0; i<60; ++i) { wall=0.01+i*(1000.0/30); __wrap_sithUpdate(); }
    if (argc == 3) { wall += atof(argv[2]); __wrap_sithUpdate(); }
    printf("%d %d %d %u\n", updates, policy, phys, sithTime_g_msecGameTime);
    return 0;
}
""")
            exe = root/("driver.exe" if sys.platform=="win32" else "driver")
            compiler = shutil.which("clang") or shutil.which("cc")
            subprocess.run([compiler, "-I"+temp, str(source), str(main), "-o", str(exe),
                            *([] if sys.platform=="win32" else ["-lm"])], check=True, timeout=60)
            for rate in (0, 1, 2, 4):
                run = subprocess.run([exe, str(rate)], capture_output=True, text=True, check=True, timeout=10)
                updates, controls, physics, game_ms = map(int, run.stdout.split())
                self.assertEqual((controls, physics), (updates, 5*updates))
                if rate == 0:
                    self.assertEqual((updates, game_ms), (60, 1020))
                    self.assertEqual(run.stderr, "")
                else:
                    self.assertLessEqual(abs(updates - (1 + 59*rate)), 1)
                    self.assertEqual(game_ms, (updates*1000)//30)
                    self.assertTrue(re.search(r"physics_us=6667,6667 control_us=33333,33333", run.stderr))
                if rate == 4:
                    for gap, min_steps, max_steps in ((240, 28, 31), (500, 1, 1)):
                        after = subprocess.check_output([exe, "4", str(gap)], text=True, stderr=subprocess.DEVNULL)
                        self.assertIn(int(after.split()[0])-updates, range(min_steps, max_steps+1))
