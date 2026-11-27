# Candidate v140 lane

Candidate v140 is the retained experimental bot client from the 2026-11-26/27
training campaign, landed as an opt-in, hash-pinned build lane. It is the
v125 stack plus four changes (the fourth as corrected by v140): the running-jump edge penalty in
`Bot_AddEdge` drops from 5.0 to 1.0 so a proven runjump leg can beat the
swim alternative in route choice (v129); all candidate diagnostic logging
sits behind a cached `JK_BOT_DIAG` environment check, off by default (v132;
the launcher passes `JK_BOT_DIAG` through only when set in its own
environment); the lift binder also recognizes the `cross0`–`cross3`
threshold-adjoin symbol names used by `C3_MTRIGELEV.COG`, so the existing
threshold step-off recovery in `Bot_LiftMove` works on C3's trigger
elevators (v138, `jkBotTraps.inc`); and a lone flag carrier camped near
home in a mutual-flag standoff hunts the opposing carrier after a 20 s
hold instead of waiting forever for a teammate that does not exist (v139,
corrected in v140 so the hold timer only counts while near base —
in-transit canal returns are never diverted; with teammates present the
stock hold/intercept split is unchanged). It does not replace the packaged
or Red default clients. The v125, v129, v132, v138, and v139 patches
remain in `native/candidate/` for the evidence trail.

## Build

```sh
python3 -B native/build_red_candidate.py \
  --red-export "$RED_EXPORT" \
  --globals-header "$GLOBALS_H" \
  --source "$SRC_A" --source "$SRC_B" --source "$SRC_C" \
  --output "$FRESH_EXTERNAL_OUTPUT"
```

The builder follows the `build_red_custom.py` chain (transfer parent receipt
`30560647…`) and additionally applies, in order:

1. `web_bots/shallow-wading.patch`
2. `web_bots/candidate/c3-door-access.patch`
3. `native/candidate/candidate-v140.patch` (SHA-256 `a8db41e8…` = the v138
   patch plus the standoff-hunt hunk in `jkBotNavigation.inc`)

Frozen receipt: `native/red-candidate-build.json`. Expected binary SHA-256:
`ddf8a24a4bd55bd4b53febb7eaf56c069f6b608433ab309fe556f8788791ed3c`,
bit-identical between the scratch experiment build that produced the v140
evidence below and this repo lane. (Earlier evidence binaries: v129
`b0892a77…` Dark Surge max-pace, v132 `0349bd76…` 1x + gate, v138
`f6e44c96…` lift binding, v139 `95f41803…` first standoff hunt.)

## What the candidate changes

- CTF C3 canal/shaft traversal: early shaft-deck edge injection, submerged
  node classification (`Bot_NodeSubmerged` down-cast fallback), dry-sector
  surf launch nodes with Force-Jump-only deck edges, Force Jump start fixes
  (submerged-from cooldown bypass, recovery-jump guard), submerged arrival
  tolerance, confined-recovery jump, wider plain-edge caps (16→22).
- Swim economics: unified breath endurance (`1000*Bot_Breath()`), swim edge
  pricing and tactic cost retune.
- BGJ Dark Surge runjump: item-endpoint admission for otherwise-unreachable
  item nodes, graded runway tolerance, slope-landing acceptance in
  `RunJump_Sweep`, phase-0 launch gate via walkable span when off-node, and
  (v129) runjump edge penalty 5.0→1.0 so the planner actually routes the
  launch leg instead of swimming.

## Evidence at landing (2026-11-27)

- C3: first completed captures were achieved on this stack's v110 base
  (5 of 12 verified 600 s matches); v125 screen: captures in 3 of 6 matches
  (red 2 / gold 1); v129 screen: captures in 2 of 6 matches, 4 total
  (red 3 / gold 1) — no regression from the cost change at this n. Capture
  reliability above ~5/12 is open. Conversion funnel pooled over v110–v138
  verified 600 s games: canal entry and far-half crossing are ~100%, enemy
  shaft-top ~85–90%, flag grab ~65% of owner-games; the dominant loss is
  the carrier return leg (canal deaths, mutual-flag standoffs at home, and
  lift waits). Sector 380's trigger lift (thing 22, `C3_MTRIGELEV.COG`)
  bound zero thresholds before v138 because the binder did not know the
  `cross0`–`cross3` symbol names; with them bound, the riding step-off
  recovery fires (98 events over 6 games on v138 vs 0 on v132), shaft-top
  rate 11/12, captures in 2 of 6 matches — in family, no reliability jump
  claimed at this n. A boarding-stop deck check and a step-off re-trigger
  in the not-riding wait were tried on scratch builds (v136/v137) and
  rejected: the deck check depressed shaft-top rate (6/12, the spawn
  gallery lift leg previously progressed by falling) and the re-trigger
  cycled carriers between sectors 380↔386. On v139 the funnel stays in
  family (shaft-top 10/12, grabs 8/12, captures in 2 of 6 matches; BGJ FF
  6.67 kills / 186 saber-fire per 100 game-s over 4 games). In a further
  12 verified v139 games exactly one mutual-carrier episode exceeded the
  20 s hold (39 s overlap), and the hunt fired as designed — the dark
  carrier's objective samples read ~20 s of `return` then `intercept` —
  though that episode ended without a capture. A matched A/B block then
  showed a consistent v139 capture dip (new block v138 6/12 vs v139 3/12
  capture-matches; pooled 8/18 vs 6/30) with funnel rates in family —
  traced to the hold timer also counting during in-transit canal returns,
  diverting live returns into hunts. v140 counts the hold only while the
  carrier is near base; across its 11 readable verified matches it
  recovers to 5/11 capture-matches and 7 captures with shaft-top 17/22
  and grabs 13/22, and BGJ FF screens at 5.83 kills / 157 saber-fire per
  100 game-s (n=4). The uncorrected v139 hunt is superseded and should
  not be used.
  At 1x on v139 (120 s ×6, 6/6 verified): canal entry 12/12 owner-games,
  far-half 9/12, enemy shaft-top 5/12, flag grabs 3/12, captures 0 — a
  full attack-and-return cycle does not fit the harness's ~172 s
  per-attempt deadline at 1x, so capture-at-1x stays unproven while
  real-time traversal to the enemy flag is confirmed.
- BGJ Dark Surge (FF sabers, rate 0, 180 s ×8): with the 1.0 penalty the
  dark bot executed 6 runjump launches, all dry ok landings, and 3 pickups
  carry a full launch provenance chain — sector-1 NAV samples, `BOT_RUNJUMP
  event=launch`, dry `event=land ok=1 wet=0` in sector 6, pickup within
  ~1.5 s (e.g. match-0004: launch t=76.40 → land t=77.66 → pickup t≈79.2).
  On v125 and v100 baselines there were 0 launches; every pickup arrived by
  swim or spawn. At 1x on the v132 binary (120 s ×12, 12/12 verified,
  receipt-checked) the result repeats: 2 proven launched pickups
  (launch, dry ok landing, pickup), each followed by a same-life exit from
  sectors 6/61 within ~1–4 s with no death in the next 30 s — the full
  `qa/bgj-dark-surge-route.json` acceptance chain in both accelerated
  practice and private 1x play. (An earlier 180 s 1x block was invalidated:
  two harness invocations raced in one output directory and the later,
  CPU-starved run overwrote the summary; 180 s also exceeds the harness's
  ~172 s per-attempt deadline at 1x. The 120 s rerun above supersedes it.)
- Sabers (same BGJ block): 6.46 kills and 152.6 sampled saber-fire per
  100 game-seconds, zero zero-contact games — in family with v110 (best
  prior cell) and v125. At larger n on v132 the earlier NF dips do not
  reproduce: BGJ NF 6.11 kills / 146 saber-fire per 100 game-s over 8 games
  (best prior NF cell 6.25/109 at n=4), BoD FF 2.85/130 and NF 1.53/56 over
  8 games each, zero zero-contact games in all 24. v138 BGJ FF spot check:
  7.50 kills / 177 saber-fire per 100 game-s over 4 games.

Full campaign record: `adjoin-training-2026-11-26-report.md` (workspace root,
not in this repo).

## Diagnostics

Investigation logging (`BOT_GRAPH_DUMP`, `BOT_LIFT`, rate-limited
`BOT_STROKE` / `BOT_ANCHOR`) is gated behind `JK_BOT_DIAG` (any value),
off by default. Measured on v132: 0 diagnostic lines across 16 BGJ owner
logs with the gate off; 1,626 `BOT_GRAPH_DUMP` lines in one game with
`JK_BOT_DIAG=1`. Gameplay with the gate off screened in family with v129
(BGJ FF 6.46 kills / 174 saber-fire per 100 game-s, 9/9 dry runjump
landings, 3 proven launched pickups; C3 verified captures 2/6 matches).

## Known limitations
- Harness training pins (`train_matches.py` receipts) still describe the Red
  policy lane; run candidate matches by pointing the harness at the
  candidate build output as in the scratch campaign.

## Open work (goal-01a21de6)

1. C3 capture reliability beyond ~2–3 of 6 matches at 600 s: carrier
   return-leg conversion (canal deaths, sector-380/605/529 dwells,
   observing the v139 standoff hunt actually fire), and a capture-at-1x
   gate if the harness deadline ever allows longer 1x games.
2. Production-lane decision: this lane is opt-in and hash-pinned but not
   wired into `train_matches.py` receipts or any default client.
