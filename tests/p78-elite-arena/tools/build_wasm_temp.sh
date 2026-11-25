#!/usr/bin/env bash
# TEMP P78 adapter engine build (copy of /workspace/pr4-port/build_wasm_feed.sh with own paths)
set -euo pipefail
export PATH=/workspace/adjoin-arena-match/venv/bin:$PATH
source /workspace/toolchains/emsdk/emsdk_env.sh >/dev/null 2>&1
emcc --version | head -1
S=/workspace/elite-arena-p78/engine-src
B=/workspace/elite-arena-p78/engine-wasm
cmake -S $S -B $B -G Ninja --toolchain $S/cmake_modules/toolchain_wasm.cmake
nice -n 5 cmake --build $B --parallel 7
echo WASM_BUILD_DONE
