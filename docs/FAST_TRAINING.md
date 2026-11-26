# Fast training: pace lanes, parallel matches, fit backends

## Private JKWeb practice

The headless browser launcher can run an experimental fixed-step engine at
1×, 2× or 4× on a loopback relay. Over a 60-game-second C3 full-Force saber
window, the two owners took 60.00 wall seconds at 1×, 30.00–30.01 at 2×,
and 14.99–15.00 at 4×. Each engine executed 1,800 policy updates and 9,000 physics updates
over an exact 60-game-second counter interval. The measured step sizes were
33.33 ms for the policy and 6.67 ms for physics at all three speeds. The 4×
trial used a separately hashed timing build, the same C3 controller, and
byte-identical JavaScript. Room startup,
joining, and team assignment add wall time before a matched opening.
[Clock counters and gameplay observations](../qa/jkweb-practice-clock.json)

Red picked up a Repeater Gun within the first game second at all three rates.
Lily cleared her airlock by 24.0 game seconds and collected a Force Boost
around 30.1 at fixed 1×. She stayed inside for all 60 game seconds at 2× and 4×.
In the earlier ordinary-clock candidate game she also stayed inside at 1×.
Each trial had the same physical starts and a fresh navigation store.
The RNG and play before placement varied across games. Use 4× to collect
practice, and evaluate behavior across repeated 1× games before promoting
the learned policy.

With Emscripten 6.0.12 active, build the practice engine in a fresh
directory outside the checkout. The builder verifies that the shipped
objects reproduce the original JS and WASM before adding the timing code.

```sh
python3 -B web_bots/candidate/build_practice_clock.py "$RUNS/clock-control"
python3 -B -m web_bots.headless host --relay ws://127.0.0.1:8080/relay \
  --seats red --host-seat lily --room-name FastCTF --episode JK1CTF --map c3.jkl \
  --mode ff-sabers --data "$GAME_DATA" --chrome "$CHROME" --runtime "$RUNS/game" \
  --engine-dir "$RUNS/clock-control" --practice-rate 4 --game-seconds 60
```

The game-time budget starts when all requested seats have joined and supplied
fresh owner clocks. Completion records each seat's first and last clock,
world epoch and observed wall duration in `headless.json`. An expired wall
watchdog or a world change fails the game-time measurement. Existing
`--seconds` measures wall time. Navigation learned with the practice clock
is retained under `practice-1x`, `practice-2x` or `practice-4x` in the navigation store.

To repeat the C3 candidate comparison, build the
[candidate object and private opening](MAP_PLAY_COVERAGE.md#reproduce-the-matched-c3-opening),
pass `--candidate-object "$JK_WEB_BUILD_ROOT/build/CMakeFiles/sith_engine.dir/src/AI/jkBot.c.o"`
to the clock builder with a fresh output directory, and supply the fixture
GOB to each room. The matched trial timed the 60 seconds after the confirmed
placements, which occur later than joining.

## Native training

Training throughput is bounded by evidence generation (native matches),
not by the offline fits. This page records the measured lanes on the
reference machine (i9-12900K, 24 threads, RTX 5070 Ti, WSL2 Ubuntu) and
how to drive them. Step identity never changes: every pace lane advances
the stock engine exactly 34 game-ms per outer step; only wall scheduling
differs. Keep evidence separated by pace lane (`--pace` on BrainStore
ingestion) until a pace-stratified comparison qualifies pooling, as
[BRAINSTORE.md](BRAINSTORE.md) requires.

## Measured single-match pace (60 requested game-seconds, Canyon Oasis)

| Rate | Wall seconds | Achieved | Verdict |
|---|---|---|---|
| 2x (previous maximum) | 35.3 | 2.0x | verified |
| 4x | 19.4 | 4.0x | verified |
| 8x | 11.4 | 8.0x | verified |
| 16x | 7.3 | 16.0x | verified |
| 32x | — | ~13x free-run | pace verification fails: one step costs ~2.1 ms here, so a 1.06 ms period is unsustainable |
| uncapped (rate 0, lane `max`) | 6.5 | ~19.5x | verified |

Boot, staging, join, and shutdown cost roughly 3 wall-seconds per match
regardless of rate, so longer matches amortize better: the harness now
accepts `--duration` up to 3600 game-seconds.

## Parallel matches

`scripts/bot_development/train_matches.py` runs matches concurrently,
each in its own loopback network namespace, and writes a `summary.json`
with per-match receipts digests and aggregate throughput. One match is
three engine processes; at high pace each is about one busy core, so the
default for accelerated practice is `cpu_count // 4` jobs. Real-time or held-out batches use one job by default so that neighbouring matches have less opportunity to distort the clock. Failed matches are retried sequentially
(`--retries 1`) because oversubscription can fail pace verification
through harness poll lag rather than engine misbehavior.

Measured aggregate throughput (120 game-second matches, uncapped):

| Jobs | Game-seconds per wall-second | Notes |
|---|---|---|
| 1 | 12.1 | |
| 2 | 24.7 | |
| 4 | 48.2 | |
| 6 | 68.8 | recommended on this machine |
| 8 | 70.8 | saturated; 1 of 8 failed verification (window tail under load) |

Against the previous best lane (one 2x match at a time, ~1.5
game-seconds per wall-second including overhead), jobs=6 uncapped is
about **46x the evidence throughput**. A 6-match, 120-second batch with
BrainStore ingestion produced 10,083 ledger decisions in 11 wall-seconds.

```sh
python3 scripts/bot_development/train_matches.py \
  --data /path/to/game-data \
  --pace-build /path/to/pace-build --client-build /path/to/red-policy-build \
  --out /outside-checkouts/run-001 --matches 24 --jobs 6 \
  --rate 0 --duration 300 --brain-root /path/to/brain --brain-profile red
```

## Fit backends (CPU vs GPU)

`bots.brain` fits are small convex logistic regressions. Measured
400-step full-batch fits (float64; torch and NumPy agree to ~1e-15):

| Rows | NumPy | torch CPU | torch CUDA (RTX 5070 Ti) |
|---|---|---|---|
| 100k | 1.48 s | 0.25 s | 1.14 s |
| 1M | 10.5 s | 3.4 s | 1.26 s |

At current ledger sizes (~10k rows, ~0.06 s) the backend is irrelevant.
Opt in with `BRAIN_FIT_BACKEND=torch` (auto device), `torch:cpu`, or
`torch:cuda` once ledgers approach a million rows; the artifact schema
is identical either way. Rendering is already skipped for headless bot
clients (`-headless` early-outs the GL draw calls), so the GPU has no
role in match simulation itself: match speed is single-core engine
compute, and parallelism across matches is the scaling axis.

## Receipt cascade

Changing `native/arena_pace.c` invalidates the pace receipt and every
receipt that pins it. The re-issue procedure used here, in order, each
with a fresh output directory outside any checkout: move the old pin
aside, build, copy the new receipt back, then update the hardcoded
parent-receipt hash in the next builder.

1. `build_arena_pace.py` -> `pace-build.json`
2. `reproduce_red_build.py duel` -> `red-policy-build.json`
   (the cc shim keeps the `sithControl` `__FILE__` literal byte-identical)
3. `reproduce_red_build.py transfer` -> `red-transfer-build.json`
4. `build_red_custom.py` -> `red-custom-build.json`
5. `build_red_platform.py` -> `red-platform-build.json`
6. `build_red_hint.py` -> `red-hint-build.json`

All six builders take `--red-export`, one or more `--source` engine
roots, `--globals-header` (the pinned generated `globals.h`), and
`--output`. Afterwards refresh the release manifest with
`python scripts/build_release.py --refresh-manifest` and re-run
`--check`.
