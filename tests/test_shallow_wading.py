"""Compile the candidate's C predicate with stock BGJ's measured surface flags and depths."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from tests.test_c3_door_access import CC
from native.tests.verify_shallow_wading import PATCH, PATCH_SHA, PATCHED_SOURCE_SHA, digest, stage


ROOT = Path(__file__).resolve().parents[1]


class ShallowWading(unittest.TestCase):
    @unittest.skipUnless(CC, "C compiler required")
    def test_shallow_bed(self):
        self.assertEqual(digest(PATCH), PATCH_SHA)
        additions = "\n".join(line[1:] for line in PATCH.read_text().splitlines() if line.startswith("+"))
        begin = additions.index("static int Bot_ShallowBed(")
        function = additions[begin:additions.index("\n}", begin) + 2]
        with tempfile.TemporaryDirectory() as folder:
            tmp = Path(folder)
            (tmp / "shallow_bed.h").write_text(function)
            exe = tmp / ("wade.exe" if os.name == "nt" else "wade")
            subprocess.run([CC, "-std=c11", "-I", tmp, ROOT / "tests/fixtures/shallow_bed.c", "-o", exe],
                           cwd=tmp, check=True, timeout=30)
            subprocess.run([exe], cwd=tmp, check=True, timeout=5)

    @unittest.skipUnless(os.environ.get("ADJOIN_WADING_NATIVE_SOURCE"), "Assembled native source required")
    def test_verified_native_application(self):
        patcher = os.environ.get("PATCH") or shutil.which("patch") or "C:/Program Files/Git/usr/bin/patch.exe"
        with tempfile.TemporaryDirectory() as folder:
            result = stage(Path(os.environ["ADJOIN_WADING_NATIVE_SOURCE"]), Path(folder) / "native", patcher)
            self.assertEqual(result["patched_source_sha256"], PATCHED_SOURCE_SHA)
