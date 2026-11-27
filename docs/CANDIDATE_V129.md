# Candidate v129 lane

Candidate v129 is the retained experimental bot client from the 2026-11-26/27
training campaign, landed as an opt-in, hash-pinned build lane. It is the
v125 stack plus one planner change: the running-jump edge penalty in
`Bot_AddEdge` drops from 5.0 to 1.0, so a proven runjump leg can beat the
swim alternative in route choice. It does not replace the packaged or Red
default clients. The v125 patch remains in `native/candidate/` for the
evidence trail.

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
3. `native/candidate/candidate-v129.patch` (SHA-256 `f3fb4f60…` = the v125
   patch, five AI files, plus the runjump edge-cost hunk in
   `jkBotNavigation.inc`)

Frozen receipt: `native/red-candidate-build.json`. Expected binary SHA-256:
`b0892a777ee8bbdd098b2f1507c3359a58581d09fb153c47e691fa06dba992b8`,
bit-identical between the scratch experiment build that produced the Dark
Surge evidence below and this repo lane.

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
  swim or spawn. This is accelerated-practice evidence; the 1x check from
  `qa/bgj-dark-surge-route.json` acceptance is still to run.
- Sabers (same BGJ block): 6.46 kills and 152.6 sampled saber-fire per
  100 game-seconds, zero zero-contact games — in family with v110 (best
  prior cell) and v125. BGJ NF and BoD NF dips versus the 2026-11-26 v1
  cells remain watch items (small n, predate v59+).

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

1. Dark Surge 1x qualification per `qa/bgj-dark-surge-route.json`
   acceptance (private 1x launched pickup + same-life safe exit).
2. C3 capture reliability beyond 5/12 at 600 s, then 1x qualification.
3. Diagnostic-logging gate with regression re-screen (BGJ/BoD/C3).
4. BGJ NF / BoD NF dip investigation at larger n.
