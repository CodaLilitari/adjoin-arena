# Candidate v125 lane

Candidate v125 is the retained experimental bot client from the 2026-11-26/27
training campaign, landed as an opt-in, hash-pinned build lane. It does not
replace the packaged or Red default clients.

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
3. `native/candidate/candidate-v125.patch` (SHA-256 `e223093b…`, five AI
   files: `jkBot.c`, `jkBotNavigation.inc`, `jkBotNavigate.inc`,
   `jkBotTactics.inc`, `jkBotRunJump.inc`)

Frozen receipt: `native/red-candidate-build.json`. Expected binary SHA-256:
`719f01177af45b93b0166e4965f299278a3a5582311d372ce4616a70f815ef3f`
(bit-identical across the layered, snapshot, and consolidated scratch builds
that produced the evidence below).

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
  `RunJump_Sweep`, phase-0 launch gate via walkable span when off-node.

## Evidence at landing (2026-11-27 scratch campaign)

- C3: first completed captures were achieved on this stack's v110 base
  (5 of 12 verified 600 s matches); v125 regression screen: captures in
  3 of 6 matches (red 2 / gold 1). Capture reliability above ~5/12 is open.
- BGJ: runjump edges form in all graphs including the cross-stream Dark
  Surge leg, and Dark Surge pickups occur, but a sector-1 *launched* pickup
  is not yet proven — observed pickups arrive by swim because the planner
  still prefers the swim leg (runjump edge cost carries a +5.0 penalty).
- Sabers: BGJ FF at parity or better; BGJ NF and BoD NF show dips versus the
  2026-11-26 candidate v1 cells at small n (watch items, predate v59+).

Full campaign record: `adjoin-training-2026-11-26-report.md` (workspace root,
not in this repo).

## Known limitations

- The patch still carries diagnostic logging from the investigation
  (`BOT_GRAPH_DUMP` canal dump at nav-ready, rate-limited `BOT_STROKE` /
  `BOT_ANCHOR`, `BOT_LIFT` injection events). Gating or stripping it changes
  the binary and needs its own measured re-screen before any production use.
- Harness training pins (`train_matches.py` receipts) still describe the Red
  policy lane; run candidate matches by pointing the harness at the
  candidate build output as in the scratch campaign.

## Open work (goal-01a21de6)

1. Planner preference so a launched Dark Surge pickup is actually chosen and
   proven with sector-1 provenance.
2. C3 capture reliability beyond 5/12 at 600 s, then 1x qualification.
3. Diagnostic-logging gate with regression re-screen (BGJ/BoD/C3).
4. BGJ NF / BoD NF dip investigation at larger n.
