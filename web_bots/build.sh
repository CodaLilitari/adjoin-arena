#!/usr/bin/env bash
# Source build; requires git, CMake, Python 3 and an activated Emscripten 6.0.12.
set -euo pipefail
project=$(cd -- "$(dirname -- "$0")/.." && pwd)
work=${JK_WEB_BUILD_ROOT:-"${XDG_CACHE_HOME:-$HOME/.cache}/adjoin-arena/jkweb"}
pin=$(cd "$project/web_bots" && python3 -B -c 'from engine_patches import BASE; print(BASE)')
if ! emcc --version | head -n 1 | grep -F '6.0.12' >/dev/null; then
    echo 'Activate Emscripten 6.0.12 before building.' >&2
    exit 1
fi
mkdir -p "$work"
work=$(cd -- "$work" && pwd)
engine="$work/source"
if [[ ! -d "$engine/.git" ]]; then
    git init -q "$engine"
    git -C "$engine" remote add origin https://github.com/tristamus/OpenJKDF2.git
fi
if ! git -C "$engine" rev-parse --verify HEAD >/dev/null 2>&1; then
    git -C "$engine" fetch --depth=1 origin "$pin"
    git -C "$engine" checkout --detach FETCH_HEAD
fi
test "$(git -C "$engine" rev-parse HEAD)" = "$pin"
python3 -B "$project/web_bots/engine_patches.py" "$engine"
git -C "$engine" submodule update --init --depth=1 lib/zlib lib/libpng
cd "$engine"
EMSCRIPTEN_ROOT=$(em-config EMSCRIPTEN_ROOT)
export EMSCRIPTEN_ROOT
# Stable __FILE__ literals keep equivalent source builds independent of the checkout path.
printf -v prefix_flags '"-ffile-prefix-map=%s=jkweb" "-ffile-prefix-map=%s/build=jkweb-build"' "$engine" "$work"
cmake -G "Unix Makefiles" -S . -B "$work/build" \
    "-DCMAKE_C_FLAGS=$prefix_flags" "-DCMAKE_CXX_FLAGS=$prefix_flags" --toolchain "$engine/cmake_modules/toolchain_wasm.cmake"
cmake --build "$work/build" --parallel "${JK_WEB_BUILD_JOBS:-4}"
python3 -B "$project/web_bots/package_engine.py" "$engine" "$work/build" --output-root "${JK_WEB_OUTPUT_ROOT:-$project}"
