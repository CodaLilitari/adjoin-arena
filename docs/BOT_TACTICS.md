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

Three more came out of the first live matches (see Evidence):

- `swim_pitch` (default 1): stock swimming thrusts along the view, and the
  forward key is twice as strong as the rise and sink keys. The bots sank
  and rose on those keys alone. A steep leg is now swum the way a player
  swims it: look along it and push forward. In the matches the median sinking
  speed went from about 0.25 to about 0.6 units a second.
- `crossing_seconds` (default 17): the engine gives twenty seconds of air.
  The bots turned back after `dive_seconds` (8) whatever they were doing,
  which made any swim longer than that impossible and, on Canyon Oasis,
  trapped them on the concussion rifle ledge: the only way off is a swim
  they kept abandoning at the bottom of the shaft. A swim whose route comes
  out on another bank may now take this long; a dive to a pickup on the
  bottom is still held to `dive_seconds` each way.
- `dive_retry` (default 45): a swim is judged before the bot gets wet, and
  one that cannot fit is refused. If a bot does turn back for air, that way
  into that water and the place it was heading for are set aside for this
  many seconds, so the same dive is not repeated at once.

Every step from a bank into water now carries `water_entry_cost`; in the
first version only one kind of entry did, and pool edges were free. The
bank exit itself is unchanged.

## Running jumps

The stock Force Jump script adds its upward speed to whatever velocity the
player already has, so a jump released at a sprint keeps the sprint through
the air. With Force Speed that crosses gaps no standing jump can. The bots'
only Force Jump was a standing one of at most 1.2 units. `run_jump`
(default 1) adds the running kind, from ordinary inputs: the run key, the
movement axes, the jump key and the two Force keys.

- **Solving.** After the ordinary graph is built, each dry node is offered
  the landings that would save it the longest way round (at least three
  times the gap plus four units) across a real gap. For each, the run-up is
  whatever straight level floor lies behind the launch node, from 0.3 units
  up to the length that reaches full speed. Launch speed follows from the
  stock rule that ground speed is thrust over drag: Force Speed adds
  0.5 + rank/2 to a thrust of 2, the run key doubles it, a strafe adds 22
  percent. The Force Jump hold (upward speed 2.5 + hold, hold at most
  0.35 per rank) is then solved so the flight comes down on the landing
  node, at no more than 2.95 units a second, which costs under ten health.
  Three flights at 94, 100 and 105 percent of the launch speed are swept
  through the level and must all find the foothold with room to stop.
- **Jumping.** The bot walks to the start of the run-up, brings up Force
  Speed if the plan needs it, stands and faces the line. The Force Jump key
  and the sprint are both timed back from one release moment, so the key
  comes up as the sprint reaches the launch node. Run-ups are often shorter
  than the stopping distance, so there is no abort once the sprint starts.
- **Using.** The planner takes such an edge only with the ranks it was
  solved for, the mana for both powers, 40 health or more, and no miss on
  that edge in the last minute. Every flight is logged to its end:
  `BOT_RUNJUMP event=edge` (what was solved), `start`, `launch` (speed
  reached against speed wanted), `land` (distance from the foothold, health
  lost), `fail` (why a jump was not attempted or missed).

On Canyon Oasis this finds the way into the concussion rifle alcove that
players use: from the lower centre platform, Force Speed, a strafing sprint
of 0.3 to 1 unit and a nearly full Force Jump, 2.1 to 2.7 units across and
one unit up. It needs Force Jump rank three or four; lower ranks find no
way in.

**Running off.** The same solver handles a ledge above water: walk or
sprint off the lip and fall in, which costs no health because the engine
quarters the vertical speed at the surface. The nearest water below is
tried first, at a walk, a run and a strafing run, once without Force Speed
and once with it, and the plan used is the one solved for the speed the bot
has at that moment. On Canyon Oasis this is the way out of the alcove: off
the south end of the ledge into the canal below. The bots still go down the
shaft when they want the rail detonator that lies in it.

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

`python -m bots.tactics list` prints the table: 27 named values with a
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

For a match, compare two groups in the same game: one on the defaults and
one with `--preset legacy`. Things to read from the logs: `BOT_MOVE` (every
ten seconds: time alive, wet, on foot, running, running refused by the
runway check, swimming pitched), `BOT_WATER` (each entry with its
destination, each exit with its length, each refused swim and each
air-return), `BOT_CONFINED` counts and whether strikes climb, and the score. If running causes
falls on a particular map, raise `run_brake` or set `strafe_run=0` before
turning `run` off.

When a build has been tried, fold the overlay into the two engine patches,
rebuild, and refresh the build receipts in the usual way.

## Evidence and limits

- 88 native fixture groups pass (79 existing, 9 new), also under
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

- Live matches: a dedicated host on Canyon Oasis with four bot clients
  built from this overlay, two on the defaults and two on `legacy` in the
  same game, positions sampled five times a second.

  | match | length | speed, new / legacy | time wet | standing still | kills |
  | --- | --- | --- | --- | --- | --- |
  | first build, 1 | 300 s | 0.48 / 0.55 | 41% / 17% | 28% / 13% | 5 / 6 |
  | first build, 2 | 240 s | 0.51 / 0.56 | 41% / 18% | 31% / 12% | 5 / 7 |
  | this build, 1 | 300 s | 0.58 / 0.47 | 25% / 31% | 12% / 21% | 6 / 8 |
  | this build, 2 | 300 s | 0.68 / 0.50 | 12% / 23% | 10% / 14% | 10 / 11 |

  The first build lost. With the concussion rifle valued properly the bots
  went and got it, and then could not leave its ledge (see `crossing_seconds`
  above). In those two matches the old bots never picked it up; in later
  ones they did, and were caught the same way. The three swim tactics are
  the answer to that. The bot profiles were swapped between the two matches
  of each pair.

- Running jumps, same host and map, every bot with Force Speed and Force
  Jump at rank four. Each bot solved six or seven jump edges. In five
  matches (about 21 minutes; four jumping bots in three of them, two in the
  others) twelve jumps were launched and all twelve landed: the ten with a
  logged landing came down 0.04 to 0.27 units from the foothold with no
  health lost, eleven of the twelve went into the concussion rifle alcove
  and one up onto a walkway. Launch speed was within 9 percent of the speed
  solved for. Fourteen more times a jump was planned and not started:
  seven with a run-up the bot could not walk, five where it was not at the
  launch platform at all, one out of mana, one knocked off the platform
  while charging. Those cost three to sixteen seconds each; the two common
  causes are now caught at once and the edge set aside. In the two matches against `legacy` the groups with
  running jumps moved at 0.59 and 0.56 against 0.47 and 0.44, were wet 22%
  and 27% of the time against 37% and 35%, and scored 6 and 10 kills
  against 6 and 6.
- Four later matches (20 minutes, four bots) with run-offs added: thirteen
  more jumps, twelve landed. The miss was Force Speed running out during
  the charge: the bot launched at half speed, fell two units and lost 23
  health. A guard against that was added afterwards and has not been run
  live. Seven run-offs from the alcove ledge all landed in the canal with
  no health lost. Each bot solved 85 to 89 jump and run-off plans.

Read the table with care. Two groups on identical settings in one 240 s
match differed by 0.48 against 0.63 in speed and 36% against 19% in time
wet, so a single match of this size cannot rank two settings. What the
matches do show: the walking, the slow sinking and the eight-second air
rule were real, and the kills are level. Nothing here shows the new
defaults winning fights.

Not established: any map but Canyon Oasis, any match with a human in it,
Full Force play, and the presets' value. Running is used for under a quarter
of the time on foot: the route follower only asks for it on straight
stretches, and the runway check refuses nearly half of those requests.
The swim pre-check and the jump controller have no fixture test; their
parts do. Twelve jumps is a small sample: nobody was shooting at most of
them, a missed jump into that alcove is a two-unit fall, and there is no
abort once the sprint starts. Running jumps have only been seen at rank
four; the solver reports a way into the alcove at Force Jump rank three
and none below. No jump across a level gap at full speed has been tried
live. Run-offs have no fixture test for their geometry, only for the choice
of plan. Force Jumps out of water, dodge jumps and firing in the air are
not built. Behaviour on moving platforms is untested.

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
