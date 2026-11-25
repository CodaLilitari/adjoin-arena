"""Exercise each packaged native engine clock with the paced tick driver on Linux."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile

NATIVE = Path(__file__).resolve().parents[1]
CLOCK = "CMakeFiles/sith_engine.dir/src/Gameplay/sithTime.c.o"
DRIVER = r"""
#include <assert.h>
#include <math.h>
#include <stdint.h>
#include <time.h>
int sithTime_g_frameTime, sithTime_g_bPaused, g_debugmodeFlags;
uint32_t sithTime_g_clockTime, sithTime_g_msecGameTime, sithTime_msecPauseStartTime;
float sithTime_g_frameTimeFlex, sithTime_g_secGameTime, sithTime_g_fps;
void SDL_Delay(uint32_t ms) { assert(ms <= 1); }
void arena_window_delay(uint32_t);
void arena_advance(void);
void sithTime_Startup(void), sithTime_SetGameTime(uint32_t);
int main(void) {
    sithTime_Startup();
    sithTime_SetGameTime(1234);
    arena_window_delay(33);
    for (unsigned i=1; i<=16; ++i) {
        arena_advance();
        assert(sithTime_g_msecGameTime == 1234 + 34*i);
        assert(sithTime_g_frameTime == 34);
        assert(fabsf(sithTime_g_frameTimeFlex - 0.034f) < 1e-6f);
        assert(fabsf(sithTime_g_secGameTime - sithTime_g_msecGameTime*0.001f) < 1e-5f);
    }
    return 0;
}
"""


def main():
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        (work / "driver.c").write_text(DRIVER)
        for kind, manifest_name, prefix in (("host", "BUILD", ""), ("bot", "BOT_BUILD", "bot-")):
            manifest = json.loads((NATIVE / (manifest_name + ".json")).read_text())
            with tarfile.open(NATIVE / (prefix + "relink-linux-x86_64.tar.gz")) as archive:
                data = archive.extractfile(CLOCK).read()
            assert hashlib.sha256(data).hexdigest() == manifest["relink_inputs"][CLOCK]
            (work / "clock.o").write_bytes(data)
            subprocess.run(["objcopy", "--redefine-sym", "stdPlatform_GetTimeMsec=arena_clock_ms",
                            "--redefine-sym", "Linux_TimeUs=arena_clock_us", "clock.o"], cwd=work, check=True)
            subprocess.run(["cc", "-std=c11", "-O2", "-Wall", "-Werror", "driver.c", NATIVE/"arena_pace.c",
                            "clock.o", "-o", "clock"], cwd=work, check=True)
            for rate in (1, 2):
                role = "dark" if kind == "bot" else "host"
                env = dict(os.environ, ADJOIN_PACE_ROLE=role, ADJOIN_PACE_RATE=str(rate))
                result = subprocess.run([work/"clock"], env=env, text=True, capture_output=True, timeout=10, check=True)
                samples = [dict(s.split("=") for s in line.split()[1:]) for line in result.stderr.splitlines()]
                first, last = samples[0], samples[-1]
                assert [int(s["frame"]) for s in samples] == [1, 5, 10, 15]
                assert all(s["role"] == role and int(s["applied_ms"]) == 34 for s in samples)
                ratio = ((int(last["game_ms"])-int(first["game_ms"]))*1e6 /
                         (int(last["mono_ns"])-int(first["mono_ns"])))
                print(f"{kind} {rate}x game/wall={ratio:.4f}")
                assert abs(ratio/rate - 1) < 0.12
            bad = subprocess.run([work / "clock"], env=dict(os.environ, ADJOIN_PACE_RATE="3", ADJOIN_PACE_ROLE=role),
                                 capture_output=True, timeout=5)
            assert bad.returncode == 64


if __name__ == "__main__":
    main()
