#!/usr/bin/env python3
"""Compile the real stock collision and pose regressions.

Requires patched bot source and a configured Unix Makefiles engine build.
Does not run a game session or qualify map traversal.
"""
from pathlib import Path
import argparse
import shlex
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--build", type=Path, required=True)
    parser.add_argument("--cc", default="cc")
    parser.add_argument("--saber", action="store_true",
                        help="Require the competitive saber overlay and its stock collision test")
    args = parser.parse_args()
    source, build = args.source.resolve(), args.build.resolve()
    flags = build / "CMakeFiles/sith_engine.dir/flags.make"
    if not flags.is_file() or not (source / "src/Engine/sithIntersect.c").is_file():
        parser.error("Need patched bot source and a configured Unix Makefiles build")
    entries = {}
    for line in flags.read_text().splitlines():
        if " = " in line:
            key, value = line.split(" = ", 1)
            entries[key] = shlex.split(value)
    command = [args.cc, "-I" + str(source / "src")]
    for key in ("C_DEFINES", "C_INCLUDES", "C_FLAGS"):
        if key not in entries:
            parser.error(f"{flags} has no {key}")
        command.extend(entries[key])
    for include in ("lib/SDL/include", "lib/SDL_mixer/include", "lib/GameNetworkingSockets/include"):
        if (source / include).is_dir():
            command.append("-I" + str(source / include))
    command += ["-UNDEBUG", "-ffunction-sections", "-fdata-sections"]
    combat = source / "src/AI/jkBot.c"
    has_saber = combat.is_file() and "#define JKBOT_HAS_SABER_TRACK" in combat.read_text()
    if args.saber and not has_saber:
        parser.error("--saber requires engine source with native/saber-combat.patch applied")
    math_sources = [str(source / "src" / name) for name in
                    ("Primitives/rdMath.c", "Primitives/rdVector.c", "General/stdMath.c")]
    with tempfile.TemporaryDirectory(prefix="jk-bot-collision-test-") as directory:
        for test, extra in (
            ("test_bot_collision", []),
            ("test_bot_saber_collision", ["Engine/sithIntersect.c", "Engine/sithCollision.c",
                                         "Primitives/rdMatrix.c", "World/sithActor.c"]),
        ):
            if extra and not has_saber:
                continue
            binary = Path(directory) / test
            sources = [str(Path(__file__).with_name(test + ".c")), *math_sources]
            sources += [str(source / "src" / unit) for unit in extra]
            if extra:
                sources.append(str(build / "generated/globals.c"))
            subprocess.run(command + sources + ["-Wl,--gc-sections", "-lm", "-o", str(binary)], check=True)
            subprocess.run([str(binary)], check=True)


if __name__ == "__main__":
    main()
