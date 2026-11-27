# Candidate v138 lane

Candidate v138 is the retained experimental bot client from the 2026-11-26/27
training campaign, landed as an opt-in, hash-pinned build lane. It is the
v125 stack plus three changes: the running-jump edge penalty in
`Bot_AddEdge` drops from 5.0 to 1.0 so a proven runjump leg can beat the
swim alternative in route choice (v129); all candidate diagnostic logging
sits behind a cached `JK_BOT_DIAG` environment check, off by default (v132;
the launcher passes `JK_BOT_DIAG` through only when set in its own
environment); and the lift binder also recognizes the `cross0`–`cross3`
threshold-adjoin symbol names used by `C3_MTRIGELEV.COG`, so the existing
threshold step-off recovery in `Bot_LiftMove` works on C3's trigger
elevators (v138, `jkBotTraps.inc`). It does not replace the packaged or Red
default clients. The v125, v129, and v132 patches remain in
`native/candidate/` for the evidence trail.

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
3. `native/candidate/candidate-v138.patch` (SHA-256 `9d9e2a29…` = the v125
   patch plus the runjump edge-cost and diagnostic-gate hunks in
   `jkBotNavigation.inc` / `jkBotNavigate.inc` and the threshold-binding
   hunk in `jkBotTraps.inc`)

Frozen receipt: `native/red-candidate-build.json`. Expected binary SHA-256:
`f6e44c96e5ac8e5167ef235c79295fa82d254a48a5bbb6e45f818fc1bcfb6627`,
bit-identical between the scratch experiment build that produced the v138
evidence below and this repo lane. (The Dark Surge max-pace evidence was
produced on the v129 binary `b0892a77…` and the 1x evidence on v132
`0349bd76…`; v138 differs from v132 only in lift threshold binding.)

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
  cycled carriers between sectors 380↔386.
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
   return-leg conversion (canal deaths, mutual-flag standoff behavior,
   sector-380/605/529 dwells), then 1x qualification (≤120 s games under
   the harness deadline).
2. Production-lane decision: this lane is opt-in and hash-pinned but not
   wired into `train_matches.py` receipts or any default client.
