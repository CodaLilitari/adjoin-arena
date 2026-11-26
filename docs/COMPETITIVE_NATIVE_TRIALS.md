# Competitive native match observations

The November 26 native block tested the new saber controller against Red's prior movement and aim in private stock games. Keep the new steering and the existing mobile Light build for further play. Both saber rulesets produced more movement input during swings. The short duels produced equal kill totals for the two controllers.

| Stock rules and map | Verified games | New saber fire samples with movement | Red control | New vs control kills |
| --- | ---: | ---: | ---: | ---: |
| Full Force sabers on Battleground Jedi | 4 | 137/160 (85.6%) | 56/166 (33.7%) | 5–5 |
| No Force sabers on Battleground Jedi | 4 | 48/75 (64.0%) | 19/99 (19.2%) | 3–3 |

Each row crosses two playing seats with two join orders. Jan and Boba start playing immediately. Each host and its two real native clients use a private loopback network. The receipts pin the loaded executable and network library. The score and fire samples use 80 game seconds after both clients join. Ordinary spawn RNG varied between games. Repeated frames within a fight describe that encounter and cannot be counted as independent matches.

An additional instrumented No Force match measured the player's actual XY position every engine frame. Boba, using the new controller, moved over 0.001 world units on 304 of 311 consecutive 34 ms intervals following saber-fire input. Jan, playing Red's control, moved on 116 of 288. Boba pitched upward on all 12 fire frames where the targeted opponent was both higher and rising. Some fire intervals still had zero movement. Seven other instrumented attempts missed the clock qualification during concurrent runs. The eight uninstrumented saber matches above all passed it.

### Light Side on Battleground Jedi

Both Light presets used Red's competitive Force decision timing against the same Dark build. Jan played once in each join order with each preset. The stock inventory exposed four stars on every selected power in all observed state samples.

| Rank-eight Light allocation | Jan kills/deaths across two games | Distinct sectors per game |
| --- | ---: | --- |
| Four stars in Jump, Speed, Seeing, Pull, Heal and Absorb | 3/5 | 20, 16 |
| Four stars in each ordinary Light power, eight unspent, stock-derived Protection | 0/1 | 5, 8 |

The pure-Light build reduced encounters. Protection was active in 71 sampled states in one match. The mobile preset covered more of this map and scored kills. Two games per allocation support keeping it as the default. They leave open whether a pure-Light bot could outperform it with different tactics or in another mode.

Jeb Springfield's BGJ FF guide describes active Absorb and four-star Pull for a Light teammate contesting the surge. His 1v1 Dark build uses four stars in each neutral power, Grip and Destruction. Trail's multiplayer guide explains the mobility and disarm tradeoffs when a Light Jedi gives up neutral powers to obtain Protection. These are historical player strategies. [Jeb's archived BGJ guide](https://www.jkdf2.net/community/jedi-knight/random-jk-history-text/paged/5/) · [Trail's guide to Force powers](https://jkdf2.net/JKBot/JKArchive/JKDF2/JKDF2/Websites/Trails%20Guide/force.html)

### No Force guns and capture the flag

Red's No Force gun baseline passed in both join orders on Nar Shaddaa Loading Terminal. The previously registered pickup/fight weights ran in four additional candidate attempts, all rejected by the clock verifier. Their scores are excluded. Any decision about a newly trained gun policy should use its own qualified held-out matches.

The crossover auditor replays frozen weights on the logged features and checks which nonzero movement the stock input reader consumed. It reports sampled changes in the player's position separately, and lists missing seat/join-order combinations for every requested map. Supply each completed or failed match directory. Include additional expected maps with another `--map` argument.

```sh
python3 -B -m scripts.bot_development.nf_crossover \
  --weights "$WEIGHTS" --weights-sha256 "$WEIGHTS_SHA256" --map m2.jkl --seconds 80 \
  "$MATCH_ONE" "$MATCH_TWO" "$MATCH_THREE" "$MATCH_FOUR"
```

In full-Force CTF on stock `c1.jkl`, the host announced two Red captures with Boba joining first, and one Gold capture with Jan joining first. Red's earlier transfer build scored one Red and two Gold captures across its corresponding games. All four games completed the 1× check. The count uses the host's flag-capture announcements. Team point totals also credit other plays. These duels establish live play through the objective cycle; a full-team CTF skill rating requires more opponents and longer matches.

The earlier Muse pace experiment supplied six fresh 120-second Canyon Oasis games each at 1×, 2×, 16× and uncapped. All 24 verified. Within 1× alone, Boba's first observed weapon gain occurred 0.748–6.460 seconds after his own spawn and Jan's occurred 1.462–39.678 seconds after hers. The first gear choice varied at every tested rate. For Jan the first weapon gain ranged from 5.134–30.192 seconds at 2× and 0.816–22.950 seconds at 16×. Unassigned spawn RNG prevents a paired timing claim across these runs. Use acceleration for practice and qualify changes at 1×.

[Match receipts, source hashes and qualification failures](../qa/adjoin-arena-competitive-native.json) · [Native build and match commands](../native/README.md#competitive-native-clients)
