# Bot movement, tactics and the coach seat

This describes the engine overlay in `native/bot-tactics.patch` and the Python
around it. It builds on the competitive bot branch and changes four things:

1. The bots run. Until now they have walked everywhere.
2. The planner stops sending bots into water for small rewards, and still
   sends them in for a heavy gun.
3. A bot that keeps moving without getting anywhere is detected and made to
   go somewhere else, for longer each time it happens again.
4. The numbers behind those decisions, and a few older ones, are named
   tactics that a file or a live controller can change without a rebuild.

**Status.** The overlay is source. It is not in the packaged binaries, which
still match `native/bot-client.patch` and `web_bots/engine.patch` and their
build receipts. It has passed fixture tests and a check against the engine's
own physics code. It has not been built into a client or played in a match.
See [Evidence and limits](#evidence-and-limits) and
[Building and trying it](#building-and-trying-it).

## The bots have been walking

The stock ground controls double a player's thrust while the run key is held
or the Always Run option is on (`sithControl_PlayerMovement`). The bot client
starts with that option off and its input code never pressed the run key, so
every bot has moved at walking speed. Forward and strafe thrust also add
without being normalised, which is why players who hold both keys and turn
the body about 35 degrees off their path move faster still.

`native/tests/run_stock_ground_tests.py` drives the engine's own ground
physics and movement control with the bot's inputs on flat ground:

| Input | Settled speed (units/s) | Relative |
| --- | --- | --- |
| Walk, as the bots moved before | 0.667 | 1.00 |
| Run key | 1.333 | 2.00 |
| Run key and the forward-plus-strafe diagonal | 1.628 | 2.44 |

Both are ordinary inputs. Neither axis ever exceeds one full key, and the
test asserts it. A player with Always Run on gets the same thrust.

## Movement

- **Run.** `Bot_Move` holds the run key only when the caller marked the
  movement as open ground and a corridor check passes: continuous supported
  floor with no drop, wall, water, thrust sector or other body for the whole
  coasting distance at the speed about to be reached, plus a quarter unit.
  Ice, water surfaces, crouching and unknown surface drag are walked.
- **Where.** The route follower asks for a run only on plain walking legs,
  and stops asking `run_brake` units before a jump, drop, lift, water edge,
  the end of the route or a corner sharper than about 25 degrees. Jump and
  water-exit timing therefore still start from close to walking speed.
  Gunfight and saber movement asks for a run whenever the corridor allows.
- **Exact thrust.** The old axes pushed up to 10 degrees off the wanted
  direction whenever the body faced elsewhere, which is most of a fight.
  The new axes put the thrust exactly on the wanted line.
- **Diagonal.** On a straight of at least `strafe_min_leg` units with a
  longer clear corridor, the bot uses both keys and, when no opponent owns
  its aim, turns its body off the path so they add up along it.

Stock Force Speed adds to thrust, so the corridor check asks for a
proportionally longer runway while it is active.

## Water

Three tactics replace the old behaviour, in which unvisited underwater
places and any small pickup counted the same as dry ones:

- `explore_wet` (default 0): underwater places earn no exploration value.
- `dive_min_value` (default 6): a submerged pickup worth less than this is
  not a destination and is not chased as equipment. A missing concussion
  rifle (18), rail detonator (12), repeater (10) or other gun (8), health
  when badly hurt (16) and shields when nearly gone (8) all still qualify.
  Ammunition top-ups and spare mana do not.
- `water_entry_cost` (default 4): added to the path cost of every step
  into water, so a dry route wins unless the swim saves real distance.

The existing failed-dive memory, breath handling and bank exit are unchanged.

## Confinement

`Bot_Recovery` already handles a bot that cannot move. The new check handles
one that moves and still goes nowhere: a bank exit that keeps failing, a jump
that keeps missing, two goals that undo each other. Positions are sampled
over `confine_seconds`. If every sample lies within `confine_radius` of their
centre, and the bot is not waiting for a lift or objective, fighting on dry
ground, or idle for want of a destination, it is confined.

Each escape drops the current goal and avoids the places being tried for
`tabu_seconds`. A repeat within 45 seconds doubles that time, up to two
minutes, and widens it to every place within 0.75 and then 1.5 units, so the
next plan has to lead somewhere else. Avoided places stay usable as
waypoints at a high cost; they are only excluded as destinations. In water
the bot also takes the existing air-and-bank escape and records the dive as
failed. Each escape logs one `BOT_CONFINED` line with position, strike
count and avoid time.

## Tactics

`python -m bots.tactics list` prints the table: 23 named values with a
default, a legacy value, and a range. The legacy column reproduces the
behaviour before this change, so one build can play both.

Values come from three places:

1. The compiled defaults.
2. A baseline file named by `JK_BOT_TACTICS_FILE` (`python -m bots.run
   --tactics-file PATH`). It is a complete revision: names it leaves out
   return to the default. The bot re-reads it when its content changes and
   rejects the whole file on any unknown name or out-of-range value.
3. A companion `tactics` command, which merges a few values into the
   current table, optionally after resetting it to the defaults.

The engine refuses a second live adjustment for 8 seconds after the last
one and reports it as `rate_limited`. Tactics outlive a death and a
controller lease, and a coach may set them while the bot is dead. A new
table does not drop the bot's current goal.

## The coach seat

With a companion lease (see the bots README), a controller can read the
table and set tactics:

```bash
python3 -m bots.companion_cli --credentials RUN/companion/BOT.json tactics-info
python3 -m bots.companion_cli --credentials RUN/companion/BOT.json tactics --preset hunter
python3 -m bots.companion_cli --credentials RUN/companion/BOT.json tactics --set gun_far=4 --set run=0
```

Over HTTP it is `GET` and `POST /v1/bots/BOT/tactics` with `preset`, `values`
and `reset`. The JKWeb client passes the same command to the browser bot.

Presets (`default`, `legacy`, `arsenal`, `hunter`, `standoff`, `dry`) are
starting points, not tuned results.

`python -m bots.coach` is a small automatic coach. It holds one preset for a
spell of at least 90 seconds, grades the spell by kills minus deaths per
minute once at least one of either has happened, and picks the next preset
with the UCB1 rule. Results persist in a memory file under a label, so later
sessions start from what earlier ones learned. It is the simplest thing that
adapts without thrashing, and a place for a smarter coach to start.

## Building and trying it

The overlay touches only `src/AI` and applies on top of either patched tree:

```bash
git apply native/bot-client.patch      # or web_bots/engine.patch on the JKWeb base
git apply native/bot-tactics.patch
```

Before a trial:

```bash
python3 native/tests/run_bot_driver_tests.py    --source SRC --build BUILD
python3 native/tests/run_bot_companion_tests.py --source SRC --build BUILD
python3 native/tests/run_stock_ground_tests.py  --source SRC --build BUILD
python3 -m unittest tests.test_bot_tactics
```

For a first match, compare two bots or two runs: one on the defaults and one
with `--preset legacy`. Things to read from the logs: `BOT_CONFINED` counts
and whether strikes climb, `BOT_STATUS` distance covered per interval, time
with a wet sector, deaths by falling, and the score. If running causes
falls on a particular map, raise `run_brake` or set `strafe_run=0` before
turning `run` off.

When a build has been tried, fold the overlay into the two engine patches,
rebuild, and refresh the build receipts in the usual way.

## Evidence and limits

- 86 native fixture groups pass (79 existing, 7 new), also under
  AddressSanitizer and UndefinedBehaviorSanitizer. The 79 existing groups
  pass with the legacy values and again with the new defaults.
- The stock ground check runs `Engine/sithPhysics.c` and the unmodified
  `sithControl_PlayerMovement` at the multiplayer physics rate with control
  updates at 30 to 60 Hz. It confirms the speeds above, that exact thrust
  holds the path at every body angle tried, and that the checked runway
  exceeds the measured coasting distance by at least 0.3 units. It has no
  level geometry, collision or networking.
- Python: tactic registry against the engine table, hub route, command
  line, launcher plumbing and the coach, including a session against a real
  hub with a simulated engine.

Not established: anything about a real map or a real match. Corner
overshoot on narrow walkways at running speed, jump accuracy after a run,
behaviour on moving platforms and the presets' value are all untested.
The bank-exit predictor is unchanged, so a bot that does enter water can
still fail to leave it; the confinement check makes that failure shorter,
not impossible.

## Human footage

Two public Full Force Canyon Oasis duels with the same camera player were
sampled as single stills: about 28 frames across the first ten minutes of
[Spidey versus Durham](https://www.youtube.com/watch?v=_tTWrQepvn4), and ten
frames between 2:00 and 30:20 of
[Spidey versus WD_Shinji](https://www.youtube.com/watch?v=XfU43kYxC88).

In every sampled frame the player is on dry ground: rock ledges, the upper
metal walkways, the canal edge. None shows the player swimming. Force
Seeing is active in nearly all of them. A long gun is in hand within about
40 seconds of the first video, and a concussion blast is visible near 6:00.

That supports treating water as a route of last resort while still going
for the heavy guns, which is what the water tactics above encode. It does
not establish how those players reached the concussion rifle, how fast they
moved, or what one player's habits say about others. Stills show no inputs.
