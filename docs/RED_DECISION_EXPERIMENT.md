# Learning a pickup decision from Red

This experiment uses Red's tactics and movement controller from commit `f453778a3cf670dea43c44315786ae4afc8ae440`. Red authored the teacher. Jan and Boba supply the two player profiles. Each plays from its own stock spawn as soon as it can act. The host begins measuring a common interval once both players have joined.

## Question

When a visible opponent and a pickup route compete for the same player's movement, can a small local model choose between continuing the route and moving to engage? Red can still aim or shoot while travelling towards a pickup. The label describes the movement decision. Red's controller handles the rest of the game, including ordinary navigation, aiming, weapon use and Force powers.

## Training and comparison

- Collect whole teacher-versus-teacher matches on Canyon Oasis and Nar Shaddaa Loading Terminal. Give both players the same stock rules, rank and game speed. Record the observations available at each eligible decision and Red's actual choice.
- Fit the model from the training matches and freeze its weights. Run a fresh script-versus-script control and a model-versus-script match for each held-out condition. Exchange which profile is under evaluation. Canyon Oasis supplies new encounters on a familiar map. Bespin Mining Station supplies a map unseen in training.
- Check offline agreement on fresh teacher decisions. In the live comparison, verify which seat loaded the weights, which decision it selected and what controls were applied. Compare engagement and score separately from agreement. Stock spawn randomness is unseeded, so even matched profiles and settings do not force the same encounter.

The preregistration fixes the match order, duration, first joiner, model seat and criteria for collecting extra training data. Earlier shared-GO studies remain available as historical fixtures. This experiment uses ordinary joining and the unmodified episode.

[Frozen schedule](../qa/adjoin-arena-red-decision-schedule.json) · [Red's implementation and match notes](https://github.com/CodaLilitari/jk-cross-server/blob/f453778a3cf670dea43c44315786ae4afc8ae440/docs/BOT_TACTICS.md)

## Keep learning while a match is being scored

The learner saves a new candidate after each completed training match with examples of both choices available across the series. Each candidate has a content hash. A bot entering a scored match loads that specific version and plays through to the end with it. Subsequent learning updates do not disturb the match.

Run the following from the repository root with NumPy installed. `RUN_ROOT` contains the match directories named in the schedule. `STATE` is a separate writable directory outside Git for retained weights and `history.json`. The watcher can run alongside the arena. Add `--include-extension` when the optional training extension is used.

```sh
python3 -B -m scripts.bot_development.analysis.red_policy_stream \
  --runs "$RUN_ROOT" --schedule qa/adjoin-arena-red-decision-schedule.json \
  --state "$STATE" --follow --finish-batch
```

Before learning from the next match, the watcher compares its previous candidate to the current practice model on Red's new decisions. Each choice must occur in at least two fresh encounters. For the first practice model, both recalls must reach 50% and balanced accuracy must exceed the training-majority rule by five percentage points. A replacement must gain at least two points in balanced accuracy and lose at most five points of recall on either choice. These checks measure imitation. Duel scores and outcomes supply separate evidence of playing strength.

To load the selected practice model for the next match, use the path printed by this command with the launcher's `--policy-weights` and `--model-side` options. A result of `teacher` selects ordinary Red play. Earlier versions remain addressable by hash. Append future training match names and maps to a separate copy of the schedule's `stream_training` list. Omit `--finish-batch` to keep watching for additions. The watcher learns exclusively from decisions made by seats controlled by Red. The scored test series stays out of training.

```sh
python3 -B -m scripts.bot_development.analysis.red_policy_stream \
  --state "$STATE" --next-practice
```

## What happened in practice

The six teaching games, eight scored games and two practice games each lasted 90 measured game seconds at 2×. Both bots began receiving control on their own join. In 26 of the 32 player starts the first eligible tick already produced nonzero movement. The longest delay to movement was 60 simulation ticks. In every match the first player was already moving before the second joined, with a lead of 1.49 to 2.99 wall seconds. [Per-player clocks and scores](../qa/adjoin-arena-red-runtime.json)

Jan entered the first practice game with weights beginning `eaa220c1`. That game's fresh scripted decisions qualified `23028e60`, which Boba loaded for the second game. The second game produced candidate `880b3f52`; `23028e60` retained its practice place. This demonstrates live updates between games. The frozen comparison recorded fewer kills for the learned players than for the scripted controls. [Model results](RED_PICKUP_MODEL.md)

To reproduce both practice updates from the original run directories, use the [schedule with the two practice games](../qa/adjoin-arena-red-practice-schedule.json) in the watcher command above. The eight scored games are reserved for evaluation. To verify the runtime evidence and practice history in a fresh output file, run:

```sh
python3 -B -m scripts.bot_development.analysis.red_run_evidence \
  --runs "$RUN_ROOT" --design qa/adjoin-arena-red-practice-schedule.json \
  --history "$STATE/history.json" --output "$NEW_EVIDENCE_FILE"
```
