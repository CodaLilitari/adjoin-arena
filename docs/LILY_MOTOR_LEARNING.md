# Lily motor learning experiment

Lily has a trainable movement policy and an executable policy loader. The first
network is an **unpromoted experiment**, not the default controller. The retained
route and skill estimates used by the adaptive policy are a separate, online
learning mechanism. Training this network does not alter those estimates.

## First measured candidate

The stock-physics replay recorded 27 successful bank escapes from nine captured
starting poses, including four yaw variants for six poses. Each demonstration
records the selected ordinary movement inputs immediately before stock player
control and physics consume them. Success requires 38 consecutive physics steps
attached to a floor in the requested dry sector. All 27 cases reached that
criterion. The resulting dataset has 4,306 control frames.

The network has 15 relative physical features, one 32-unit tanh hidden layer, and
six outputs: forward, strafe, turn, pitch, jump probability and duck probability.
It has no absolute world-position input. Training uses NumPy; deployed inference
uses the Python standard library. Export embeds the exact weights and inference
code in a single ABI-1 policy, so the live loader hashes the whole candidate.

| Evaluation | Result |
| --- | ---: |
| Training frames / captured-pose groups | 3,431 / 7 |
| Held-out frames / captured-pose groups | 875 / 2 |
| Held-out axis mean squared error before fitting | 0.38896 |
| Held-out axis mean squared error after fitting | 0.18565 |
| Held-out jump/duck binary accuracy | 85.89% |
| Closed-loop bank-escape score of the learned network | Not measured |
| Multiplayer or human-opponent score of the learned network | Not measured |

Every yaw variant of a captured pose stays in the same split. This prevents
nearby versions of a held-out starting state from entering training. All examples
still come from one map and a simplified actor fixture. The axis error remains
substantial, and button accuracy can benefit from an imbalanced label distribution.
Neither metric measures strategic competence or traversal success.

The checked-in candidate is `bots/lily/models/water_bc_v1.json`; its self-contained
policy is `bots/lily/policies/water_bc_v1.py`. Model provenance includes the source,
map and demonstration digests and the exact split identities. The raw retail map,
private recordings and experience databases are not included. The candidate is
enabled only by explicitly staging it and supplying a current `learned-motor`
directive. No launcher selects it automatically.

## Reproduce collection, training and export

Use your owned extracted map and the pinned patched source described in the build
receipts. The build directory supplies the same generated headers and compiler
flags used by the native regression suite.

```sh
python native/tests/stock_water_replay/collect_motor.py \
  --source "$PATCHED_NATIVE_SOURCE" --build "$NATIVE_BUILD" \
  --map "$OWNED_JKL" --output "$NEW_PRIVATE_DEMO_DIRECTORY" \
  --compare-baseline qa/bots-bank-landing.json

python -m bots.lily.train_motor "$NEW_PRIVATE_DEMO_DIRECTORY"/*.jsonl \
  --output candidate.json --epochs 200 --hidden 32 --seed 23
python -m bots.lily.export_motor_policy candidate.json --output candidate.py
```

The collector compiles once, runs every case, records both failed and successful
outcomes, and writes a receipt. The trainer accepts only physically successful
episodes with matching applied action identity. It excludes interrupted,
censored, failed and mismatched samples. An optional `split_group` groups related
episodes; otherwise the episode itself is the split unit. At least two independent
successful groups are required. Related demonstrations must be given the same
group by the data producer.

Every accepted live training row matches a physical terminal on its scoped episode ID, integer action sequence and SHA-256 policy identity. The native sample's revision must match the full policy hash's 32-bit wire revision. Its owner must be running, its source sample must match the recorded attempt, and the attempt, observation and outcome must share an identity and life fence. Sequence zero is reserved for an identified native-baseline stock-water demonstration with its supported dry landing criterion. Old live motor samples that repeat an initial direction and distance without a world endpoint are excluded. Historical stock-water demonstrations already measured the direction and remaining distance to the dry node at every tick. The original 4,306 replay samples remain eligible.

The exported policy takes a fresh, fenced operator directive whose `goal` is `learned-motor` and whose `parameters.position` is a fixed world-space endpoint. Each inference recomputes the relative direction and remaining distance from the current pose. It waits within 0.001 game units of the endpoint. The target must be within 100 game units to produce a motor action. Optional `parameters.duration_ms` accepts 1..600 and defaults to 550 ms. Its outputs
still pass through native command validation and ordinary player controls.
Demonstration control ticks and a deployed motor chunk can have different timing;
that difference is another reason to require physical evaluation before promotion.
Use the staging and rollback procedure in [the controller guide](LILY_ADAPTIVE.md).

## What live replacement actually proved

The [integration receipt](../qa/lily-adaptive-live.json) records three bounded
stock-physics probes through the real native JKCP socket, authenticated companion
HTTP service, supervisor process and policy child processes. Each ran against a fixed engine binary.

The first deliberately simple forward-and-turn policy took control underwater.
Two revisions produced ordinary inputs, a broken candidate was rejected and the
baseline resumed when the supervisor stopped. The actor did not reach the dry
bank during that probe. Thirty-seven short displacement goals nevertheless
received positive physical verdicts. This is a concrete warning about reward
design: small local movement is not the task of escaping the water.

The revised plumbing probe lets the baseline complete swimming and airborne
movement before taking over on supported dry ground. In that run, both executable
revisions activated and applied inputs, the deliberately broken replacement was
rejected, and baseline control resumed after supervisor shutdown. The actor also
established the required dry landing. These are control and handover results.
The probe policies are not the trained network and do not establish a competitive
advantage.

A third run exercised the same dry-ground handoff with the `forward-probe` skill. Its two revisions produced 25 and 224 attributed control samples. Across 30 action outcomes, 29 reached their short displacement criterion and one was censored at shutdown. The subsequent offline readback opened the same SQLite database in an independent supervisor. At the same recorded pose, identical fresh policy workers made different validated motor decisions. An empty database supplied the 0.5 prior and the probe policy selected a 250 ms sidestep. The reopened database supplied three wins in three scored attempts, giving a smoothed probability of 0.8 and a 250 ms forward stride. The first controller's physical trace independently contains those three outcomes. The fresh workers ran after the fixture ended and both proposals were captured before transport. Attributed rows now carry a fixed endpoint and current remaining distance, and 241 samples from that trial passed the training filters. They were excluded from the previously fitted candidate.

A case-by-case comparison matched all 27 disabled-seat landings to the historical bank matrix on case, yaw, landing sector, health and supported dry time at millisecond precision. The largest difference between an unrounded recorded duration and the published rounded time was 0.000334 seconds. The receipt identifies the exact reference and collection digests.

## Development target

The next learned controller should choose temporally extended skills with explicit
termination and task-level outcomes: escape the water, acquire a specific useful
pickup, disengage with health remaining, or win an engagement. A short physical
displacement is supporting evidence. It must not stand in for those outcomes.

The first candidate's limitations motivate recurrent physical context, terrain
features, diverse successful demonstrations and direct closed-loop evaluation.
Cloning the existing controller can initialize a skill. Improvement beyond that
controller needs outcome-based optimization and comparisons against the same
starting conditions. Opponent-conditioned tactics and self-play need recorded
engagements, consistent reward attribution and repeated matches.

The live loader supports that work by letting a trusted local candidate contain
new executable skill logic or new model weights. Retained experience survives
policy changes. A tactical operator can issue a fenced directive through the
existing owner, and a candidate can take over after the current undertaking ends.
The system does not yet generate code autonomously, run continuous neural training,
or promote its own experiments on the strength of prediction loss alone.
