# Candidate v132 lane

Candidate v132 is the retained experimental bot client from the 2026-11-26/27
training campaign, landed as an opt-in, hash-pinned build lane. It is the
v125 stack plus two changes: the running-jump edge penalty in `Bot_AddEdge`
drops from 5.0 to 1.0 so a proven runjump leg can beat the swim alternative
in route choice (v129), and all candidate diagnostic logging sits behind a
cached `JK_BOT_DIAG` environment check, off by default (v132; the launcher
passes `JK_BOT_DIAG` through only when set in its own environment). It does
not replace the packaged or Red default clients. The v125 and v129 patches
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
3. `native/candidate/candidate-v132.patch` (SHA-256 `b1da3d2d…` = the v125
   patch, five AI files, plus the runjump edge-cost and diagnostic-gate
   hunks in `jkBotNavigation.inc` / `jkBotNavigate.inc`)

Frozen receipt: `native/red-candidate-build.json`. Expected binary SHA-256:
`0349bd7604cf04b41052da5cbf20949fe6ede2fb0470c880971460faf7a51cb6`,
bit-identical between the scratch experiment build that produced the gate
evidence below and this repo lane. (The Dark Surge evidence was produced on
the v129 binary `b0892a77…`; v132 differs only in gated diagnostic output.)

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
  reliability above ~5/12 is open.
- BGJ Dark Surge (FF sabers, rate 0, 180 s ×8): with the 1.0 penalty the
  dark bot executed 6 runjump launches, all dry ok landings, and 3 pickups
  carry a full launch provenance chain — sector-1 NAV samples, `BOT_RUNJUMP
  event=launch`, dry `event=land ok=1 wet=0` in sector 6, pickup within
  ~1.5 s (e.g. match-0004: launch t=76.40 → land t=77.66 → pickup t≈79.2).
  On v125 and v100 baselines there were 0 launches; every pickup arrived by
  swim or spawn. At 1x on the v132 binary (120 s ×12, 12/12 verified,
  receipt-checked) the result repeats: 2 launches, both dry ok landings and
  both proven launched pickups, each followed by a same-life exit from
  sectors 6/61 within ~1–4 s with no death in the next 30 s — the full
  `qa/bgj-dark-surge-route.json` acceptance chain in both accelerated
  practice and private 1x play. (An earlier 180 s 1x block was invalidated:
  two harness invocations raced in one output directory and the later,
  CPU-starved run overwrote the summary; 180 s also exceeds the harness's
  ~172 s per-attempt deadline at 1x. The 120 s rerun above supersedes it.)
- Sabers (same BGJ block): 6.46 kills and 152.6 sampled saber-fire per
  100 game-seconds, zero zero-contact games — in family with v110 (best
  prior cell) and v125. BGJ NF and BoD NF dips versus the 2026-11-26 v1
  cells remain watch items (small n, predate v59+).

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

1. C3 capture reliability beyond 5/12 at 600 s, then 1x qualification.
2. BGJ NF / BoD NF dip investigation at larger n; BoD re-screen on v132.
