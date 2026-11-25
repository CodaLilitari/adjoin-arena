# Red’s pickup and engagement learner

The model learns one movement decision from Red’s native controller. Given a visible opponent and a viable stock pickup route, class 1 asks the bot to keep pursuing the pickup, and class 0 gives movement to combat. A bot can aim and fire while pursuing a pickup. Navigation, collision, weapons, Force, aiming and most other decisions remain with the controller. The label records Red’s choice at the arbitration point, before later steering, Force actions, traps or route failures can override it.

## Native inputs and inference

The nine integers, in order, are health, shields, enemy distance, item distance, selected weapon, applicable ammunition, pack flag, wet flag and remaining route nodes. Distances are in thousandths of a world unit. The learner receives the state available before the decision. Player names, match/map identity, tick number, Red’s answer, the actual controls and future inventory or score are excluded from its inputs.

The dense network has nine inputs, eight rectified linear hidden units and one signed output. All 89 weights and biases are fitted. The ASCII file starts with **RED_NEURAL_V1 9 8**. The next two lines are nine integer centers and nine positive scales. Each of the eight hidden-unit rows contains its bias and nine input weights. The output row contains its bias and eight hidden weights. Weights represent real numbers multiplied by 1,024, and biases by 1,048,576. Native inference normalizes the features, clamps inputs to ±2, applies the rectifier with a cap of 32 and evaluates the output in integer arithmetic. A zero or positive score selects class 1.

## Fit and reproduce

The input is a [predeclared whole-match schedule](../qa/adjoin-arena-red-decision-schedule.json). Training ingests both seats’ native BOT_DUEL records from the training runs. Class support alone can trigger the scheduled extension. A new encounter begins on a seat, life, target or item change, or after a gap exceeding 0.6 game seconds. Each nonempty match has the same initial weight. Encounters divide that weight equally and repeated identical feature/label pairs within each encounter count once. Remaining mass is balanced across classes. A model may learn a tactical rule directly from enemy distance. Source and deployed feature vectors contain the range observable at that tick.

Training uses Python 3 and NumPy. Full-batch Adam trains for 320 steps with PCG64 seed 20261125, learning rate 0.025 and L2 coefficient 0.0001 on the weight matrices. Only training observations determine normalization and weights. Python and native inference both use the exported quantized network. A fixed SHA-256 identifies the candidate used during each measured live match.

The first fit used six whole matches on Canyon Oasis and Nar Shaddaa. Its 167 encounters yielded 4,948 eligible decisions. Red chose to turn and fight 1,265 times and to pursue the pickup 3,683 times. The conditional training extension was unnecessary. Rebuilding the 492-byte model from the 60,362-byte compressed corpus with Python 3.13.15 and NumPy 2.5.4 reproduced its SHA-256, `23028e60d4203b06f9fb88abb29aaf0ea15082b57501cd869acef9feafdf8171`. [Training receipt](../qa/adjoin-arena-red-decision-training.json) · [Training corpus](../qa/adjoin-arena-red-decision-training-corpus.json.gz) · [Frozen weights](../bots/models/red_pickup_engage_v1.weights)

The compact training corpus retains only decision rows and their source-log hashes. Each includes its encounter, seat, life, decision sequence, simulated time, target and item identity, nine inputs, teacher, selected and resolved-pickup bits, and fire/movement indicators. It contains no account or session credential, private game data, chat or game media. Model reconstruction writes a new file or verifies an identical existing file.

From the repository root, reconstruct the frozen candidate:

~~~sh
python scripts/bot_development/analysis/red_tactical_policy.py rebuild --corpus qa/adjoin-arena-red-decision-training-corpus.json.gz --train-receipt qa/adjoin-arena-red-decision-training.json --model reproduced.weights
~~~

From private raw match logs, the equivalent collection commands are:

~~~sh
python scripts/bot_development/analysis/red_tactical_policy.py train --schedule qa/adjoin-arena-red-decision-schedule.json --runs /path/to/runs --model candidate.weights --corpus training-corpus.json.gz --receipt training.json
python scripts/bot_development/analysis/red_tactical_policy.py evaluate --schedule qa/adjoin-arena-red-decision-schedule.json --runs /path/to/runs --model candidate.weights --train-receipt training.json --receipt held-out.json
~~~

## Interpretation

For automatic activation, the [policy registry](../bots/models/red_pickup_registry.json) looks up the exact game mode, guns or saber rules, Force availability and level-content digest. A V1 gear-policy cell needs a fresh teacher-controlled match with both labels and balanced accuracy above the training majority, and a frozen-model match with nonzero engine movement reads for both choices. These checks qualify an imitation experiment for that exact context. CTF objective decisions, saber engagements and unknown levels use the native controller. Map navigation can learn costs independently of the neural decision. To add an independently verified study, use the [registry builder](../scripts/bot_development/analysis/qualify_red_policies.py) and keep the corresponding weights beside its registry.

At this exact teaching point the original choice is a 0.45 world-unit enemy range threshold inside additional eligibility checks. The evaluation also scores that known rule on rounded native observations. Correctly imitating the branch demonstrates teacher-to-weights transfer for one decision. Tactical improvement requires better gameplay outcomes in independent matches.

On the fitting corpus the rounded range rule reproduced every label. The network agreed on 4,836 of 4,948 decisions. All 112 disagreements were decisions to fight at enemy ranges between 0.450 and 0.509 world units, where Red continued toward the pickup. This interval identifies clips worth inspecting when coaching the choice.

The held-out script-controlled matches measure imitation against Red and the constant majority class from training. The native model matches measure actual selections, resolved movements, and disagreements with the shadow Red decision on the states the model reached. For live uptake, a resolved engagement requires movement controlled by the combat branch, and a resolved pickup pursuit requires movement controlled by the supply branch. A stationary or overridden tick cannot count as either. These are encounter-correlated decisions. The matches use fresh unseeded spawns. Improvement in playing strength requires independent outcome evidence.

## First held-out results

Four fresh teacher-controlled matches yielded 2,260 eligible decisions across 83 encounter groups. Both players contributed. The 492-byte network reproduced 926 of 927 decisions to engage and 1,237 of 1,333 decisions to continue a pickup. The trained model’s main error was giving up the pickup early. [Held-out evaluation and raw-log digests](../qa/adjoin-arena-red-decision-heldout.json)

| Teacher-controlled data | Accuracy | Balanced accuracy |
|---|---:|---:|
| Frozen neural policy | 95.71% | 96.35% |
| Always continue the pickup (training majority) | 58.98% | 50.00% |
| Red’s known range rule on the rounded observation | 99.96% | 99.95% |

Four separate live matches put the frozen weights in charge of one player. Python inference matched all 1,109 native selections. The model chose engagement 228 times and pursuit 881 times. Matching nonzero engine input reads verified 65 engagements and 813 pursuits. A fire button was active on 388 pursuit frames. The model disagreed with the shadow teacher 13 times. One example occurred 2.924 game seconds into the dark-seat Bespin run, on decision 16 of Boba’s first life. The enemy was 0.465 units away. Red would have continued toward the pickup. The model engaged and the engine read forward −1.0 and slide +0.890278.

| Map and tested profile | Red subject kills/deaths | Neural subject kills/deaths |
|---|---:|---:|
| Canyon Oasis, Boba Fett | 1 / 3 | 2 / 1 |
| Bespin, Boba Fett | 3 / 3 | 0 / 2 |
| Canyon Oasis, Jan Ors | 1 / 0 | 1 / 1 |
| Bespin, Jan Ors | 2 / 0 | 1 / 2 |
| **Combined** | **7 / 6** | **4 / 6** |

The equal number of deaths and three fewer kills give no evidence of improved competitive strength. Bespin was absent from training. There the candidate scored 90.05% balanced accuracy and produced 65 verified fight reads and 290 pursuit reads, qualifying the exact FFA/guns/Force/Bespin combination for the optional imitation registry. Canyon scored 98.89% balanced accuracy. Its 523 verified pursuit reads and zero verified fight reads keep that cell on Red.
