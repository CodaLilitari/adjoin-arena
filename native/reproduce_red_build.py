"""Reproduce either frozen Red image, including its original stock diagnostic filename."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

NATIVE=Path(__file__).resolve().parent
RECIPES={
    "duel":("build_red_policy.py","/tmp/adjoin-red-yk4obou6/source/src/Devices/sithControl.c"),
    "transfer":("build_red_transfer.py","/tmp/adjoin-red-fj8jyjnc/source/src/Devices/sithControl.c"),
}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind",choices=RECIPES)
    args,other=parser.parse_known_args()
    script,original_path=RECIPES[args.kind]
    real_cc=shutil.which("cc")
    if not real_cc: parser.error("cc is required")
    # Existing receipts also pin their original builder files. Supply the
    # exact diagnostic expansion without changing either builder or game.
    with tempfile.TemporaryDirectory(prefix="adjoin-cc-map-") as tmp:
        shim=Path(tmp)/"cc"
        shim.write_text("#!/usr/bin/env python3\nimport os,sys\n"
                        "args=sys.argv[1:]\n"
                        "source=next((a for a in args if a.endswith('/source/src/Devices/sithControl.c')), None)\n"
                        f"if source: args=['-fmacro-prefix-map='+source+'={original_path}',*args]\n"
                        f"os.execv({real_cc!r},[{real_cc!r},*args])\n")
        shim.chmod(0o755)
        subprocess.run([sys.executable,"-B",NATIVE/script,*other],
                       env=dict(os.environ,PATH=tmp+os.pathsep+os.environ["PATH"]),check=True)


if __name__=="__main__":
    main()
