# Competitive play and continued learning

Red's script plays immediately. It controls movement, weapons and mode objectives and supplies training examples. The learned decision considered here is narrower. In a gun match, when the bot is already pursuing a pickup and sees a legal opponent, it can keep pursuing or turn to fight. Unknown maps use Red's ordinary navigation, and map-specific route experience persists under the level digest. A pickup/fight model has no authority over flag scoring or saber rules.

Wren supplied the JKWeb seats and live takeover controls. Lilivane supplied the observation policy. Muse Code supplied the persistent BrainStore, model fitters and fast match runner. The integration adds ruleset-aware coaching, data partitions, repeatable training, stock pickup attribution and the saber fixes. [Native match results](COMPETITIVE_NATIVE_TRIALS.md) · [Saber movement and geometry](../qa/saber-tracking.md)

## Coaching a playing bot

Run this against a local headless room. Use the weapon rules of the room and the actual seat name in its manifest.

```sh
python -m bots.coach_seat --run /path/to/headless.json --seat red \
  --start lilivane --weapons sabers --interactive
```

Lilivane chooses a defensive distance when hurt, seeks an arsenal with a weak gun in gun games, and returns to the default tactics after recovery. The 12-game-second dwell begins when the engine acknowledges the change. Manual `preset`, `set` and `strategy` commands take the seat. Enter `lilivane` for her observation policy, `auto` for Wren's learning coach, or `release` to give control back to the bot. Wren's coach can persist its preset rewards with `--brain-root`, an engine digest and a label specific to the map, rules, and pace. Lilivane's authored policy updates its choice from current observations.

In a private 1× Canyon Oasis NF saber match, Red earned one scored window for the default preset (+4). A new coach process read that result and tried the unplayed hunter preset. A manual strafe adjustment was acknowledged, grading paused during nine game seconds of manual control, and the automatic coach regained the seat. Two coaches grading the same profile concurrently also retain both updates in the regression suite. [Browser restart and handback](../qa/jkweb-live-coach-persistence.json) · [Two-coach test](../tests/test_coach_shared_memory.py)

## Training

Wren's browser coach and native pickup network have separate playing paths. Browser learning can retain preset rewards between sessions. The exported pickup weights drive the native gun-mode controller.

Run from the repo root with private game files and an external directory for every run and BrainStore. Two seat logs from the same verified native match share one partition. The playing binary, map, rules and each seat's clock come from the receipt. Experimental controller configurations carry their own cohort tag. A repeated import retains the earlier result. A different partition for the same log is refused. Route statistics stay out of the holdout. A training cohort contains one set of rules, one engine build and one pace. Accelerated practice is available. Scored matches here use 1× game time.

```sh
python -m bots.brain --root "$BRAIN" ingest-receipt "$PRACTICE_RUN" --split practice
python -m bots.brain --root "$BRAIN" ingest-receipt "$BLIND_RUN" --split holdout
FEATURES=health,shields,enemy_mm,item_mm,weapon,ammo,pack,wet,remaining_route_nodes
python -m bots.brain --root "$BRAIN" train-decision --kind pickup_engage \
  --features "$FEATURES" --scope ffa/guns/noforce --pace 1x --build "$ENGINE_SHA" \
  --outcome-weighted --teacher-fraction 0.5 --out candidate.json
python -m bots.brain --root "$BRAIN" export-red candidate.json --out candidate.weights
python -m bots.brain --root "$BRAIN" qualify-decision --kind pickup_engage \
  --model candidate.json --native candidate.weights --pace 1x
```

The teacher fraction reserves half the fitting weight for Red's demonstrated choices, balanced between fighting and continuing. The remainder learns from attributable outcomes. The importer attributes a score or health change once per choice type and life. A same-life gain in the local player's weapon mask can reward a supply decision. Ammo refills, shield-only pickups and flag events do not supply pickup rewards. Stationary, Force and navigation overrides end the previous attribution window. Shadow scores use independently controlled teacher actions. Incoming receipts preserve each actor's measured game-clock interval and hash its complete log. Older rows without a known match partition remain available for inspection; re-import their verified matches to use them in a fresh training cohort. Rare actions and matches with no eligible decision are important when interpreting a high overall agreement. Reserve whole games before fitting. Use fresh evaluation games after changing a candidate in response to a score.

For continuing practice, pass `--brain-root "$BRAIN" --fit-next` to the native batch runner. Each practice batch adds verified games to the store and writes the next candidate alongside its summary. `--active-side alternate --swap-join-order` pins the selected BrainStore incumbent at the start of the next batch and crosses both controlled sides with both joining orders over four runs. The same arguments work with a specific challenger using `--model-side alternate --policy-weights candidate.weights` in place of `--active-side alternate`. See `python scripts/bot_development/train_matches.py --help` and the [engine and game-data setup](../native/README.md). Separate output roots preserve old logs and candidates. Use `--jobs 1` for real-time evaluation on a shared machine.

## November 26 pickup/fight challenger

The final candidate combined all 2,446 Red demonstrations from five verified practice games with 59 decisions that had attributable gameplay outcomes. The trainer gave the script and outcome data equal total weight. Training and scoring used the same stock Red transfer executable. The ordinary native client and JKWeb client have separate build identities.

The eight accepted 80-game-second NF guns matches crossed both seats and both joining orders on each map. Twelve attempts were recorded in total. Four missed their 1× clock checks and were excluded. One missing M2 combination was rerun on its own after the other games finished. The native checker verified the loaded weight digest, replayed each eligible model prediction and inspected the engine's movement readback.

| Map | Challenger vs Red frags | Challenger wins / losses / draws | Native fight / pickup movement inputs |
|---|---:|---:|---:|
| Canyon Oasis (`m10.jkl`) | 6–6 | 1 / 2 / 1 | 273 / 1,402 |
| `m2.jkl` | 1–0 | 1 / 0 / 3 | 0 / 169 |

Red stays the default. The candidate scored seven frags to six and split the eight games 2–2 with four draws. It handled both decisions on Canyon Oasis. On M2 it delivered no fight inputs, and two seat/order combinations produced no executed pickup/fight decision with observed movement. The independent teacher shadow had 1,499 eligible choices from Canyon Oasis and 80.0% balanced agreement. M2 supplied no eligible teacher actions for that score. A positive aggregate frag margin does not resolve that missing comparison. Four later Nar matches placed the opponents near the rifle in stock room 61. With the same V3 weights and 40 seconds per match at 1×, the native input reader consumed 116 fight choices and 528 pickup choices with movement. Four fresh ordinary-spawn games produced zero fight choices and 93 pickup choices with movement. The close opening gives the coach a reproducible situation for training both actions. The ordinary spawns still leave deployment performance unresolved. [Nar opening comparison](../qa/nar-close-opening.json)

[Scored matches and admission decisions](../qa/competitive-learning/nf-v3-results.json) · [Native weights](../qa/competitive-learning/nf-challenger-v3.weights) · [Training coefficients and cohort](../qa/competitive-learning/nf-challenger-v3.json)

An additional 50-game-second practice match exercised the ordinary batch runner with `--active-side dark --fit-next`. The store had no promoted weights for that cell, so Red played. Its 383 new choices increased the persistent practice set from 2,446 to 2,829. The runner wrote a different native policy for the next trial, while leaving the active controller on Red. The earlier challenger and its scored games remain reproducible.

## Promotion and rollback

First verify the exported integer policy against independent Red decisions. Then play it against the script in both seats and joining orders at 1× on the deployment map. Count frags, deaths and how often the candidate actually controlled a choice. Check for regressions by map and seat. Clock-rejected trials retain their receipt and contribute no score. CTF needs stock flag events, and saber movement needs actual player displacement. Keep collecting practice data while a challenger is under evaluation.

After a successful evaluation, register the native weights for the exact rules, map and engine. The active selection is read at the next batch start. Use rollback to restore the prior qualified generation. Rolling back the first generation restores Red's script.

```sh
CELL="ffa/guns/noforce|$MAP_SHA|$ENGINE_SHA"
SHA=$(python -m bots.brain --root "$BRAIN" register candidate.weights --kind pickup_engage --scope "$CELL")
python -m bots.brain --root "$BRAIN" promote "$SHA" --kind pickup_engage --scope "$CELL" --safety-ok --heldout-ok
python -m bots.brain --root "$BRAIN" rollback --kind pickup_engage --scope "$CELL"
```

The promotion flags record a deliberate approval after reviewing match evidence. The live browser coach can change tactics during play. The native pickup network loads a generation at match launch. This preserves an identifiable opponent and policy in every scored game.
