# BrainStore: persistent learning across matches

`bots/brain.py` gives each bot profile one local brain that survives
matches and processes. It complements the existing learners; it does not
replace them:

| Existing system | BrainStore relationship |
|---|---|
| Tactics registry + coach UCB | Live policy parameters stay in `bots/tactics.py`; BrainStore can register and promote artifacts, it does not send tactic commands. |
| Red pickup model | Its frozen `.weights` files register here by hash with scope and metrics. |
| Lily SQLite experience | Live route/motor evidence stays in Lily's store; BrainStore keeps the cross-system decision ledger and model registry. |
| Native nav recall | `.nav` penalties and `BOT_NAV_LEARN`/`BOT_EDGE_ATTEMPT` logs ingest into persistent edge statistics. |

## Layout

A brain root (outside Git, outside per-run directories) contains
`brain.sqlite3` (decisions and edge statistics), `manifest.json`
(active models and history), and `models/<sha256>.bin` artifacts.
One profile owns one root; opening a root under another profile name
is refused.

## What persists

- **Decision ledger.** Kind, map digest, rules scope, policy hash,
  pre-decision features, legal candidates, teacher choice, selected
  choice, applied movement, and later outcome. This is the distillation
  dataset for turning scripted decisions into weights.
- **Edge statistics.** Per level digest + scope + directed geometry
  key: attempts, successes, failures, traversal-time and damage sums,
  last-seen features. Unlike the native recall cache (128 penalties,
  24-hour expiry), BrainStore statistics do not expire; versioning is
  by map digest and scope instead.
- **Models.** Candidates are copied in by SHA-256. Promotion requires
  explicit safety and held-out gates; the previous active model stays
  available for rollback. Promotion never happens from training loss
  alone.

## Global edge model (unseen maps)

`fit_edge_model` trains a small deterministic logistic model over
map-independent geometry features (distance, height change, route
mode, water flags, destination item, base cost, node degrees). On a
map the bot has never visited, the runtime graph is still built from
the loaded level geometry; this model supplies the prior success
estimate for each legal edge, and per-map BrainStore statistics become
the residual evidence after attempts. Map names and arbitrary sector
IDs are memory keys only, never predictive inputs.

Native telemetry for training comes from `BOT_EDGE_ATTEMPT` lines
(transfer trace on): geometry features plus arrive/stall outcome for
every directed edge the planner actually drove.

## Native integration (regenerated tactics overlays)

The regenerated `native/bot-tactics.patch` and
`web_bots/bot-tactics-web.patch` carry `jkBotBrainModel.h` (portable
SHA-256 + strict `ADJOIN_EDGE_V1` parsing + inference, standalone-tested
by `native/tests/run_bot_brain_model_tests.py`) and `jkBotBrain.inc`:

- `Bot_SearchPaths` adds a capped predicted-failure surcharge
  `(1 - P(success)) * 4` per edge when a hash-verified artifact is
  configured via `JK_BOT_EDGE_MODEL` + `JK_BOT_EDGE_MODEL_SHA256`
  (the `ADJOIN_EDGE_MODEL*` spellings are also accepted). No artifact
  means shipped routing, byte for byte. Transfer builds keep their own
  prior only when the tactics planner prior is absent
  (`JK_BOT_BRAIN_PLANNER_PRIOR` guard), never both.
- With `JK_BOT_TRACE_DECISIONS=1`, goal, weapon-switch, and Force-cast
  choices emit `BOT_DECISION kind=goal|weapon|force` lines with the
  numeric features the scripted policy saw, for ledger ingestion and
  distillation. The tactics driver fixture proves the prior flips a
  Dijkstra route and that removing it restores the shipped route; the
  full Linux bot-driver suite (98 PASS groups) compiles and passes
  against the regenerated native tactics tree, the web bot
  translation unit compiles under Emscripten 6.0.12 with the project's
  own compile command, and the full native engine links and boots to
  its menu stack against retail Steam assets under Xvfb. A live
  multiplayer qualification match (dedicated host + arena launcher)
  has not been run with these builds yet.

## Training pace lanes

BrainStore evidence must keep accelerated and ordinary-speed experience
separate until parity is proven for the task being learned. Adjoin Arena
already has two distinct fast paths:

- **Uncapped stock-physics replay.** The single-actor fixture preserves the
  chosen control interval and 150 Hz physics sequence, but only sleeps when
  `LILY_REPLAY_REALTIME` is set. This is the mass-rollout lane for motor,
  route-edge, jump, swim, and recovery scenarios. Its pool-90 receipt found
  byte-identical traces at 1x and uncapped, with a 16.19x median speedup on
  that one case; that result does not by itself qualify networked matches.
- **Paced native multiplayer.** The optional arena pace images keep each
  outer simulation step at exactly 34 game ms, scheduling it every
  34/rate real ms in the host and both clients. Rates 1, 2, 4, 8, 16, and
  32 are scheduled; rate 0 is uncapped (no sleep, lane label `max`). On
  the reference machine 16x is the highest sustainable scheduled rate and
  uncapped achieves roughly 19x; `scripts/bot_development/train_matches.py`
  runs these matches in parallel at about 46x the old single-match 2x
  throughput (see [FAST_TRAINING.md](FAST_TRAINING.md)). This is the
  present full-match self-play lane. Networking, companion leases, and the
  launcher still use wall time, the three processes have independent
  deadlines, and the qualified evidence is opening-focused rather than a
  deterministic full-match replay guarantee. Lane labels follow the rate:
  `1x`, `2x`, `4x`, `8x`, `16x`, `32x`, or `max`.
- **Ordinary-speed qualification.** Promotions still need 1x native matches
  and, where the claim covers it, the browser build. The WASM/headless path
  has an FPS cap for rendering cost, not the native virtual-clock hooks.

Decisions and edge statistics carry dedicated `pace` (and decisions a
`build`) column: pass `--pace 1x|2x|replay-uncapped` on ingestion so
evidence stays separated by lane. Do not pool 1x, 2x, and uncapped replay
outcomes into one fitness estimate without a pace-stratified comparison.
Prefer simulation ticks and game milliseconds for learning windows; wall
time is only throughput and liveness evidence.

## Distillation and suggestion (offline)

`fit_decision_model` / `train_decision_from_store` distill any binary
ledger kind over caller-chosen features into the same small logistic
artifact shape as the edge model; `leave_one_map_out_decisions` scores
each map with a model that never trained on it. `ingest_decision_log`
imports existing native telemetry (`BOT_GEAR` goal plans, `BOT_SWITCH`
weapon changes, `BOT_FORCE_INPUT` casts) beside `BOT_DUEL`.
`suggest_tactics` fits a ridge reward model over tactics trial history
and returns one bounded advisory step; applying it remains a coach or
operator decision through the ordinary tactics path.
`fit_outcome_model` / `train-decision --outcome-weighted` move past
imitation: ledger rows with recognized outcome fields (kill, death,
capture, pickup, damage, route success/failure) are weighted by
exp(advantage / temperature) against their own action's mean reward,
so actions that worked in context count more while failures are never
deleted. This is offline advantage-weighted regression, not on-policy
reinforcement learning; promotion still needs the safety and held-out
gates above. `export-red` converts a Brain decision model over the
native `BOT_DUEL` features into `RED_NEURAL_V1` integer weights (the
logistic head embeds as relu(z) - relu(-z) under the native input
standardization), so an outcome-trained head can drive the existing
Red pickup inference path live. In a side-swapped pair of 60-second
matches the converted outcome model went 3 kills / 2 deaths against
the teacher's 2 / 3 while disagreeing with it on roughly a quarter of
duels — proof the artifact loads and changes live decisions, at far
too small a sample for a skill claim. `qualify-decision` computes the shadow side of those
gates (labelled rows, map coverage, balanced accuracy, rewarded-row
agreement quality) and reports every refusal reason as JSON. Coach
bandit statistics round-trip through `import-coach` / `export-coach`
in the existing `bots.coach` memory shape, keyed by label and build,
so preset learning persists in the same store as everything else.
Both live coach front ends also accept `--brain-root` (with
`--brain-profile`) to load and persist that record directly in
BrainStore instead of a separate JSON memory file.

## Live qualification (verified locally)

Retail JK assets are installed locally (Steam `Star Wars Jedi Knight`,
including `JK1MP.GOB`), user namespaces work, and the complete native
chain was rebuilt in WSL from a local frozen export carrying the
regenerated tactics overlay: planner-go, pace, Red policy, and transfer
clients all accepted their re-issued receipts. One wrinkle found while
rebuilding: the cog-generated `globals.h` pin embeds the original
builder's absolute source path in a comment, so that pin was
regenerated at the local reproducible path and the receipt cascade
re-issued from there.

Five arena matches then passed the launcher's own
`live_join_and_loadout_verified` gate (60 requested game seconds each):
Red policy at 2x and 1x without an edge prior, transfer at 2x without
one (121 edge attempts collected), transfer at 2x with an edge model
trained from those attempts, and transfer at 2x with that same model
on first-visit stock map `m4.jkl` (151 more edge attempts). Both bots
logged `BOT_BRAIN_MODEL ... status=loaded` for the exact artifact
trained in the same session. Their logs were cycled into one
persistent BrainStore: 4,892 decisions and 305 aggregated edges, with
teacher and outcome-weighted pickup models trained and
shadow-qualified on live evidence. Scores and counts are in the
[live qualification receipt](../qa/brain-live-qualification.json);
they are completion evidence, not a controlled skill comparison.

Map holdout is deliberately mixed: pickup decisions trained only on
Canyon Oasis scored 0.857 balanced accuracy on `m4.jkl` (0.985 in
reverse), while the current global edge model scored 0.5 in both live
leave-one-map-out directions because stalls are rare (18 failures in
419 attempts) and geometry alone does not yet separate them. Per-map
edge residuals still persist and are reused on return visits; broad
cross-map edge discrimination needs richer support/mechanism features
and more failure examples.

## Commands

```sh
python -m bots.brain --root BRAIN --profile red init
python -m bots.brain --root BRAIN --profile red ingest-edge-log RUN/client.log \
  --map-sha <jkl-sha256> --scope ffa/guns/force
python -m bots.brain --root BRAIN --profile red train-edge --out edge-model.json \
  --native-out edge-model.txt   # prints the JK_BOT_EDGE_MODEL_SHA256 digest last
python -m bots.brain --root BRAIN --profile red register edge-model.json \
  --kind edge_model --scope global
python -m bots.brain --root BRAIN --profile red status
```

Promotion additionally requires `--safety-ok --heldout-ok` after the
candidate has passed held-out whole-match and safety evaluation; see
`promote --help`. No BrainStore command issues a game input, and no
artifact activates itself.
