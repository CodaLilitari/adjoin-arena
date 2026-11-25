#!/usr/bin/env bash
# Source build; requires git, CMake, Python 3 and an activated Emscripten 6.0.12.
set -euo pipefail
project=$(cd -- "$(dirname -- "$0")/.." && pwd)
work=${JK_WEB_BUILD_ROOT:-"${XDG_CACHE_HOME:-$HOME/.cache}/adjoin-arena/jkweb"}
engine="$work/source"
pin=7a6f95c9a3399e59acbf019dc6b25f9981d29dff
if ! emcc --version | head -n 1 | grep -F '6.0.12' >/dev/null; then
    echo 'Activate Emscripten 6.0.12 before building.' >&2
    exit 1
fi
mkdir -p "$work"
work=$(cd -- "$work" && pwd)
engine="$work/source"
if [[ ! -d "$engine/.git" ]]; then
    git clone --no-checkout https://github.com/tristamus/OpenJKDF2.git "$engine"
    git -C "$engine" checkout --detach "$pin"
fi
test "$(git -C "$engine" rev-parse HEAD)" = "$pin"
python3 -B "$project/web_bots/engine_patches.py" "$engine"
git -C "$engine" submodule update --init lib/zlib lib/libpng
cd "$engine"
cmake -S . -B "$work/build" --toolchain "$engine/cmake_modules/toolchain_wasm.cmake"
cmake --build "$work/build" --parallel "${JK_WEB_BUILD_JOBS:-4}"
python3 "$project/web_bots/package_engine.py" "$engine" "$work/build"
