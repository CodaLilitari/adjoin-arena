# Fast training: pace lanes, parallel matches, fit backends

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
