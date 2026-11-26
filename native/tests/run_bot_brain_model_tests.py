#!/usr/bin/env python3
"""Check the BrainStore edge-model artifact without engine libraries or assets."""
from pathlib import Path
import argparse
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--cc", default="cc")
    args = parser.parse_args()
    source = args.source.resolve()
    if not (source / "src/AI/jkBotBrainModel.h").is_file():
        parser.error("Apply the regenerated bot-tactics.patch to the pinned engine first.")
    with tempfile.TemporaryDirectory(prefix="jk-bot-brain-model-") as directory:
        binary = Path(directory) / "test_bot_brain_model"
        subprocess.run([args.cc, "-std=c11", "-Wall", "-Wextra", "-Werror",
                        "-I" + str(source / "src"),
                        str(Path(__file__).with_name("test_bot_brain_model.c")),
                        "-lm", "-o", str(binary)], check=True)
        subprocess.run([str(binary)], check=True)


if __name__ == "__main__":
    main()
