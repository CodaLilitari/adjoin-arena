"""C3 candidate regressions. The full Windows graph check uses an owned stock episode."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

from scripts.bot_development.analysis.c3_door_stalls import DOOR_SCRIPTS, resource
from web_bots.engine_patches import PATCHES


ROOT = Path(__file__).resolve().parents[1]
PATCH = ROOT / "web_bots/candidate/c3-door-access.patch"
LLVM = Path("C:/Program Files/LLVM/bin/clang.exe")
CC = os.environ.get("CC") or shutil.which("clang") or (str(LLVM) if LLVM.exists() else shutil.which("cc"))


def run(args, directory):
    result = subprocess.run(args, cwd=directory, text=True, capture_output=True, timeout=90)
    if result.returncode:
        raise AssertionError(result.stdout + result.stderr)
    return result.stdout


class C3Access(unittest.TestCase):
    def test_stays_experimental(self):
        self.assertNotIn(PATCH.name, PATCHES)
        self.assertTrue(PATCH.is_file())

    @unittest.skipUnless(CC, "C compiler required")
    def test_key_and_geometry_rules(self):
        diff = PATCH.read_text().split("+++ b/src/AI/jkBotC3Door.h\n", 1)[1].split("\n--- ", 1)[0]
        header = "\n".join(line[1:] for line in diff.splitlines() if line.startswith("+")) + "\n"
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            (temp / "jkBotC3Door.h").write_text(header)
            exe = temp / ("access.exe" if os.name == "nt" else "access")
            run([CC, "-std=c11", "-DC3_ACCESS_CANDIDATE", "-I", temp,
                 ROOT / "tests/c3_door_access.c", "-o", exe], temp)
            self.assertIn("regression passed", run([exe], temp))

    @unittest.skipUnless(os.name == "nt" and CC and all(os.environ.get(n) for n in
                         ("C3_ENGINE_SRC", "C3_GLOBALS_DIR", "C3_EPISODE")),
                         "Windows Clang, engine headers, generated globals and owned JK1CTF required")
    def test_stock_bindings_and_full_search(self):
        """Use the packaged AI sources and real engine structs with fixture world and file services."""
        engine = Path(os.environ["C3_ENGINE_SRC"])
        bots = Path(os.environ.get("C3_BOT_SRC", engine))
        episode = Path(os.environ["C3_EPISODE"])
        manifest = json.loads((ROOT / "web_bots/BUILD.json").read_bytes())["changed_sources"]
        patcher = shutil.which("patch") or "C:/Program Files/Git/usr/bin/patch.exe"
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            for name, digest in manifest.items():
                if not name.startswith("src/AI/"):
                    continue
                data = (bots / Path(name).relative_to("src")).read_bytes()
                self.assertEqual(hashlib.sha256(data).hexdigest(), digest, name)
                target = temp / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            run([patcher, "-p1", "-F0", "--batch", "--binary", "-i", PATCH], temp)
            for name in ("jkl/c3.jkl", *("cog/" + script for script in DOOR_SCRIPTS)):
                target = temp / name
                target.parent.mkdir(exist_ok=True)
                target.write_bytes(resource(episode, name))

            # The whole production TU compiles. Internal linkage in this fixture lets the linker
            # discard unrelated game entry points whose callers live in the rest of the engine.
            api = temp / "src/AI/jkBot.h"
            api.write_text(re.sub(r"(?m)^(int |void |flex_t )(?=jkBot_)", r"static \1", api.read_text()))
            shim = temp / "windows-headers.h"
            shim.write_text("#define WIN32_LEAN_AND_MEAN\n#include <winsock2.h>\n#include <windows.h>\n"
                            "#include <mmsystem.h>\n#include <unknwn.h>\n#undef near\n#undef far\n"
                            "#undef small\n#undef min\n#undef max\n")
            tu = temp / "fixture.c"
            tu.write_text('#include <assert.h>\n#include "AI/jkBot.c"\n#include "c3_door_graph.c"\n')
            exe = temp / "graph.exe"
            run([CC, "-std=gnu11", "-O1", "-ffunction-sections", "-fdata-sections", "-Wl,/opt:ref",
                 "-DARCH_64BIT", "-DNO_JK_MMAP", "-DQOL_IMPROVEMENTS", "-DSTDSOUND_NULL",
                 "-D_USE_MATH_DEFINES", "-include", shim, "-I", temp / "src", "-I", engine,
                 "-I", os.environ["C3_GLOBALS_DIR"], "-I", ROOT / "tests", tu, "-o", exe], temp)
            result = run([exe], temp)
            self.assertIn("actual edge registration and Dijkstra alternate route", result)
            self.assertIn("stock map, live COG binding", result)


if __name__ == "__main__":
    unittest.main()
