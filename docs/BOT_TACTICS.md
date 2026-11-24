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
own physics code, and bot clients built from it have played bot-only matches
on Canyon Oasis. It has not been played against people.
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

`water_slip` (default 1): a bot that ends up in water on a leg meant for
dry ground (it walked off a pool edge, or a jump fell short) no longer
presses jump at the surface toward a ledge no hop can reach. In the first
recorded match that loop splashed five times in four seconds. It sets the
leg aside for 15 seconds and replans from the water, which routes it out
through a checked bank exit or a Force Jump from the surface. In a 300 s
match the two bots on the defaults slipped seven times and were out within
2 to 6 seconds each time.

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

**Out of the water.** The stock Force Jump also fires from the water
surface, and the bots never used it: their only way out was the surface
hop, 0.7 up and 0.6 across. The solver now looks for banks above an open
surface. The swimmer floats at the start of a short swim toward the bank,
holds the jump key for the length of the swim and lets it up a little short
of the wall, so the body is above the lip when it gets there and its
swimming speed carries it over. On Canyon Oasis this finds four exits, from
the oasis pool up to the walkways 1.17 above the water. They need nearly a
full rank-four jump, so the hold is timed to 1.33 seconds.

## Dodging

The bot is told about every shot fired at it, and until now only used that
to turn on the shooter. With `dodge_jump` (default 1), an explosive shot
that will burst within 0.45 units of the bot in 0.3 to 1.6 seconds sets a
short Force Jump: 0.2 seconds of hold, which lifts the body 0.7 units for a
little over a second and lands slower than the speed that hurts. The jump
keeps the ground speed the bot had and leaves its aim free, so it goes on
firing in the air. Each one logs a `BOT_DODGE` line, and `BOT_MOVE` counts
dodges and seconds of firing while airborne.

## Heavy guns

The concussion rifle has two modes in the stock COG. The shell (primary)
flies at 7 units a second and bursts for 80 within 0.8 units, the shooter
included, for 8 power cells. The beam (alternate) is an instant thin ray that
does 80 to the first thing it meets within 5 units, with no splash and no
harm to the shooter, for 4 cells. Either mode needs 8 cells in hand to fire.
The old rule used the beam first anywhere it reached. With `conc_alt_range`
(default 1.4) the bot fires the shell beyond 1.4 units when the shell is
safe, and the beam inside that or when the shell would catch the bot or an
ally; 99 restores the old rule.

A heavy gun (concussion rifle or rail detonator) had to show a safe shot on
every frame to stay selected. No other gun had to. A target stepping behind
a lip, or the muzzle path clipping a wall for a moment, put the heavy away,
and picking it back up costs the switch time twice. A combat jump put it
away too, because heavies may not fire in the air. With `heavy_hold`
(default 1) the heavy stays in hand while the beam reaches, while the target
is out of sight, and while the shot is only blocked, since a blocked path
blocks every gun alike. It is still put away for real reasons: out of ammo,
the target inside its own blast, splash on an ally. A combat jump holds fire
instead of switching. In a dodge hop the bot fires a heavy if the kick (80
force units back along the body) still lands on floor or against a wall.
`BOT_SWITCH` logs every switch away from a heavy with a visible target and
the reason; `BOT_MOVE` counts shells and beams with mean range, seconds with
a heavy in a fight, and those switches.

## Force Pull

The stock Pull takes whatever player, actor or item lies nearest the view
centre, in sight, within 0.5 + rank/2 units. A player loses the gun in hand
and drops to fists, unless Absorb is up; fists and sabers cannot be pulled.
Pulls on players were reviewed with a check 0.8 s after each release: in
three matches 128 of 199 checked pulls disarmed (64%), much the same for
both groups. Absorb, which the light-side bots keep up in fights, accounts for
most of the rest; the existing per-opponent retry delay already backs off
after a pull that changes nothing. Pulls cancelled before release (the
stock marker named something else, or sight was lost) were 102. Each cancel
cycles the selected power, which is the scrolling power names seen in the
recording; that is only on the bot's own screen.

Items answer Pull too: the item flies at the puller with gravity off.
Keys, wrenches and CTF flags refuse it. With `item_pull` (default 2; 0 =
never) a bot standing on dry ground with no enemy in sight pulls an item
worth at least that much (the same value the planner gives it) from 0.75
units out to just inside its reach. It stops, turns until the item is
centred, holds Pull until the stock marker names that item, releases, and
stands for up to 1.5 s to catch it. A wrong marker cancels through
deselection; an item that was not caught rests ten seconds before another
try; an enemy coming into view ends the pull. `BOT_PULL` lines record each
item pull and each player pull's outcome.

## Mines and thermals

The bots used neither. The combat code left thermal detonators and
sequencer charges out of weapon choice, and the planner never collected
them. Canyon Oasis has a thermal pickup and three charges.

`hazard_avoid` (default 1): a weapon thing at rest with an explosion of its
own is a hazard. That is a laid charge (a proximity mine two seconds after
it lands, for sixty seconds, set off by anything inside 0.3 units), a
bouncing thermal on its fuse, or a stuck rail charge. Nodes within reach of
one are avoided, legs that pass one cost as much as an avoided node, and a
bot standing too close steps away. Shots in flight stay with the dodge.

`mines` (default 1): charges are worth collecting up to three. When the bot
takes a guarded item that respawns (a heavy gun, armour, health, a power
boost) and has a charge, it selects the charge, raises it and drops a
proximity mine (the secondary) on the spot, for the next player who comes
for the respawn. Not with an enemy in view, not near another hazard, not
with more than three of its own alive, not in team play or while any
player is peaceful.

`thermals` (default 1): thermals are worth collecting up to four. The
stock throw scales the grenade's launch velocity by the seconds held, 0.7
to 2 for the primary, which bursts on whatever it touches: 0.7 units of
reach at the shortest hold, 3.2 at the longest, with up to a second and a
third of flight. That suits targets guns serve badly: out of sight below or
behind a lip, in the water, or standing still, 1.4 to 3.2 units away. The
bot flies the grenade the way the engine does (template velocity, air drag,
gravity, collision with level geometry) to find the pitch that lands by
the target's feet, chooses the shortest hold that reaches, keeps the arc
updated while holding, and releases once turned onto it. It never throws
at its own feet. `BOT_MINE`, `BOT_THERMAL` and `BOT_HAZARD` lines log each
attempt.

## Use

Every press of the use key plays the stock "use" animation, and the host
sends it to every player, whether or not anything is there to use. The bot
pressed use every 0.8 seconds whenever its way was blocked, in case it was
a door. In a match that came to 30 to 63 presses a minute. With `blind_use`
at its default of 0, it presses only when the engine's own activate test
would find something: a COG-linked surface or a captured thing that is not
an item, within reach along the view. A stall that triggers recovery still
presses once. Measured in the same match: 2 to 3 presses a minute, against
30 and 63 for two bots with `blind_use=1`.

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

## What the recordings showed

Two four-minute recordings of one bot's own rendered client on Canyon Oasis,
reviewed frame by frame against its logs, were set beside four public Canyon
Oasis matches between people (two Full Force duels, a 2v2 and a permanent
concussion rifle duel). Each fix below is a tactic whose legacy value keeps
the old behaviour.

- `quick_respawn` (default 1). The stock controls ignore the respawn key
  until three seconds after death, then respawn on a press followed by a
  release. The bots pressed for 0.18 s in every 1.4 s from 1.5 s on, so the
  first press that counted came 4.3 to 4.5 s after death; the players in the
  footage were back in about 3.1 s. The bot now presses on alternate frames
  as soon as the stock timer allows. In a match: 3.0 s dead per death
  against 4.5 s for the legacy group.
- `air_health` (default 0; legacy 30). A swimmer under 30 health turned for
  air at once, breath or no breath. The surface heals nothing, and the turn
  set the goal aside and replanned, which on the shaft-top pool put a bot at
  23 health in and out of the same water about ten times in twenty seconds.
  Breath alone decides now. A hurt bot gets to health through the plan, and
  swims still cost more under 40 health, as before.
- `swim_cost` (default 3; legacy 1). A leg swum under water costs three
  times its length in the planner: swimming runs at 0.27 to 0.6 units a
  second against 1.3 to 1.6 for running. The step in from a bank keeps its
  `water_entry_cost`. In 25 minutes of one of the people's matches, sampled
  every 1.5 seconds, no stay in water was longer than about four and a half
  seconds; the recorded bot's single swims ran 7.6 to 11.6.
- `water_fight` (default 1). The climb out of water took the view and never
  fired. In one recording two bots sat in the same small pool for eight
  seconds, on the same exit, each in the other's reach, neither shooting,
  until both were caught as confined. People fire while swimming up a shaft
  and come out of a pool with the gun up: one fired the concussion rifle 0.7
  seconds after dropping out of the bottom of the shaft. Now:
  - The exit no longer demands facing the bank. Forward and strafe together
    push at full thrust along the line to the bank with the body turned up
    to 43 degrees off it, facing either way along it. The climb looks as near
    the shot as that allows and fires when on it. A concussion rifle or rail
    detonator, which kicks its shooter 80 force units back, waits out the
    run-up, the jump and the last settle on the launch spot.
  - A launch spot belongs to the swimmer nearest it. The other gives way,
    sets that way out aside for four seconds and plans another
    (`BOT_WATER event=yield`).
  - On a level swim leg in a fight, the stroke is solved for the view:
    forward along the view, strafe at 0.7 of it, rise and sink at half, so
    the bot keeps looking at its target while it swims.
  - A Grip is answered even in the middle of a climb; other powers wait for
    dry ground.
- `fjump_standstill` (default 1). The bot stops before a Force Jump and the
  stock release adds only upward speed, so the leg is flown on air thrust
  from a standstill. Integrated the way the engine applies thrust in the air,
  that carries the body only 0.1 to 0.2 units across, even at full charge. The arcs that admitted Force Jump legs assumed running speed
  through the air, so they took legs the bot then fell short of, into the
  wall under the ledge; in one recording a bot spent most of 40 seconds in a
  corridor facing its rock wall between Force Jumps. Legs are now checked by
  flying that standstill flight through the level, level and slightly lower
  landings included, which the old check skipped. Ledges that need speed are
  for the running jumps. The route moves on to the landing once the bot is
  within 0.11 of the launch node, and a few hundredths off that spot can be
  enough to fall short, so the bot first steps back onto the spot, still
  facing the landing, and jumps from there. A leg that cannot be made even
  from the spot, or that the bot cannot get back onto in three seconds, is
  struck off and the bot plans again (`BOT_JUMP event=refuse`). Before this,
  the second recording's corridor had the bot walking into the rock wall
  under such a leg for 20 seconds.
- `jump_memory` (default 30; legacy 0). A Jump or Force Jump leg that comes
  down somewhere other than its target is struck off for twice this many
  seconds, and every spot on the ledge it aimed at is set aside for this
  long, so the next plan finds another way up or another goal
  (`BOT_JUMP event=miss`). A landing on the target's own level, a short walk
  from the mark, counts as made.
- `speed_upkeep` (default 1). Force Speed costs 20 mana and lasts 5 + 2.5 x
  rank seconds. The players kept it up nearly all the time, recasting every
  few seconds. The bot cast it only for a long straight walk and kept 200 mana
  back for Absorb. It now keeps Speed up on any walking leg and in fights,
  past the Absorb reserve, but never below the mana for a Jump and a Pull,
  and not during jumps, drops, lifts or swims. Within 1.5 units of an
  opponent, where Grip takes hold, it still leaves the mana to raise Absorb.
  In a match the group on the defaults had Speed up about 215 of every 300
  seconds alive, against about 165 for the legacy group. `BOT_MOVE` reports
  the seconds Speed was down by reason (`speed_no`: another power in
  progress, navigation or water state, movement input, a leg with its own
  pace, mana, the ground ahead). In an eight-bot match, before the
  close-range rule, Speed was up 66 to 80 percent of the time alive; water
  and navigation states accounted for most of the rest, mana and blocked
  ground for a few seconds each.
- `resupply` (default 1). A pulled gun is a new pickup (`+fpconcrifle` and
  the like): takeable after 0.2 s, gone after 4 s, never respawned. The bots
  disarm a lot (73 disarms by four bots in one six-minute match) and left
  the guns lying. Now a pulled gun at rest, or sliding to a stop, is worth
  what that gun is worth (a missing concussion rifle 18). A bot with no gun
  holding more than a few shots adds 4 to every real gun, so they keep their
  order, treats ammunition for a gun it holds as worth at least 12, and does
  not go hunting. A pickup just chosen is favoured by half again for 2.5
  seconds (otherwise 15 percent), so near-equal choices do not flip back and
  forth at a waterline, where path costs jump. An opponent left with fists is
  preferred as a target and in the hunt. `BOT_GEAR event=loose` logs each
  pulled gun chased; in one eight-bot match there were eleven.

Two earlier tactics came from the first recording:

- `absorb_reserve` (default 1). The bot took Grip damage again and again
  without answering it. Absorb costs 200 and at rank four turns Grip,
  Lightning and Destruction damage into mana. While it is down, optional
  casts leave enough mana to raise it, and a Grip is answered with
  Protection or Absorb before bacta, whose cooldown would delay them. While
  the Grip lasts, nothing optional is cast, only Healing below 60 health, so
  the mana is there when Absorb runs out and must be raised again: in one
  recording the bot spent it on Pulls during a Grip and died when Absorb
  expired.
- `turn_rate` (default 1800). The bot turned through the keyboard axis, which
  the stock code caps at 200 degrees a second for yaw and 90 for pitch. It
  now turns the way a mouse does, through the stock look code, up to this
  many degrees a second straight onto the point; 0 restores the keyboard.

The fists-as-peace setting is taken out for now: bots read `fists_peace` from
their behaviour file but ignore it, so a player with fists out is an
opponent like any other.

## Tactics

`python -m bots.tactics list` prints the table: 46 named values with a
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
- Eight further matches (40 minutes): 48 jumps and run-offs launched, 46
  landed. One jump reached only two thirds of its sprint speed and fell
  short; one run-off was thrown aside in the air by a blast. Out of the
  water, two attempts with an earlier timing showed the Force Jump does
  fire from the surface, and both fell back. The present timing has not
  yet been tried in a match: the bots were rarely in that pool.
- A four-minute recording of one bot's own rendered client, third person,
  against two bots on the same build: 3 kills, 3 deaths, about a third of
  the time in water, six dodges, three seconds of firing in the air, no
  running jumps. Reviewing it frame by frame found the blind use presses
  and the surface-hop loop above. It also shows the Force power names
  filling the top of the bot's own screen. That comes from the bot cycling
  its selected power to stop Pull, which only the bot itself sees, and from
  36 Pull casts in 277 seconds alive. The video also shows the bot taking
  Grip damage repeatedly without answering it.
- The match after both fixes, 300 s, defaults against `legacy`: speed 0.63
  against 0.38, time wet 21% against 40%, kills 7 against 3, use presses
  1.9 to 5.5 a minute against 9 and 27.
- Three matches (16 minutes) of the defaults against the defaults with
  `conc_alt_range=99`, `heavy_hold=0` and `item_pull=0`. The new group
  fired 26 shells at a mean range of 3.0 to 3.2 units and 2 beams where the
  shell was not safe; the old group fired only beams, 12 of them, at a mean
  of 1.2 to 2.8. Both fire the rifle less often than it is in hand. In the
  last match, the one with
  the blocked-path rule built in, the new group put a heavy away 9 times
  (5 out of ammo, 4 too close) and the old group 29 times, 13 of them for a
  path that was only blocked. Kills over the three were 28 to 23 and deaths
  21 to 31. The first of the three had no blocked-path rule yet, and one
  match of this size cannot rank two settings (see below). 32 item pulls
  were cast and 23 items caught, among them a full shield, a repeater, a
  crossbow and a stormtrooper rifle. An earlier match caught a concussion
  rifle.
- The driver suite (73 groups) passes with the legacy values, with the new
  defaults and under the sanitizers; it now covers the shell and beam rule,
  holding a heavy through a blocked path, firing in a dodge hop, an item
  pull from aim to catch, hazards, laying a mine and a thermal throw from
  selection to release.
- The fixes from the recordings: the driver suite (82 groups, 7 of them new)
  passes with the legacy values, with the new defaults and under the
  sanitizers. Running the older groups on the new defaults needs a few of
  them to pin a tactic whose change is deliberate: swim pricing in one graph
  with hand-set edge costs, the running-arc Force Jump model in two arc
  tests, and an armed bot in one pickup-value test.
- Three matches on Canyon Oasis with eight bots (16 minutes). Defaults
  against `legacy`, six minutes: 60 kills and 42 deaths against 40 and 58;
  3.0 s dead per death against 4.5; 80 seconds of firing while wet against
  23; two exit spots given way. Defaults against the defaults with
  `water_fight=0`, bot profiles swapped, six minutes: 43 and 49 against 48
  and 46, time wet 15% against 17%. That match does not show water fighting
  changing the score or the time in water; most firing in water already
  happens outside the climb out (33 against 38 seconds). An all-default
  match of four minutes: eleven pulled guns chased.
- Five more four-minute recordings of the bot's own client, each reviewed
  against its log before the next change. They found the corridor wall
  (above, `fjump_standstill`), a bot dithering at a pool's edge right after a
  respawn while its pickup choice flipped between near-equal guns (the
  resupply ordering and hold), Pulls spent during a Grip (above,
  `absorb_reserve`) and Speed down for long stretches with mana spent on
  Absorb. The last recording, with everything above, still shows long swims
  through the canal tunnel after a run-off from the alcove ledge, and a death
  under Grip once Absorb was down and mana was short.
- Four matches on Canyon Oasis with mines on (23 minutes): 12 mines laid,
  14 steps away from a bot's own fresh mine, none from anyone else's. The
  charges lie on a ledge the planner does not reach; five of the six bots
  that laid mines got them with Item Pull. Whether a mine killed anyone is not measured. No thermal was thrown:
  the map's one thermal lies in the pool where the planner has no node, and
  no bot picked it up. On m5, which has four of each, the bots barely move
  (fifty confinement escapes each in six minutes) and its heavy guns are
  unreachable to the planner, so it was no test.

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
of plan, and neither have the jumps out of water. Dodge jumps and firing
in the air are built and happen, but whether they save health is not
measured: in one 300 s match four bots dodged 17 times and two of them fired
for 3 seconds in the air. After one jump fell short at 9 percent under its
sprint speed, jumps must now land at 90 and 109 percent of it, which halves
the ways into the alcove at rank four (three are left). Behaviour on moving platforms is untested.
Thermal throws are tested only in fixtures so far. Mines are laid only on
item spots, not on a retreat. Grip is now answered with Protection or
Absorb, also mid-climb out of water; whether that saves health is not
measured. Whether the beam's 0.8 degree aim tolerance is what
keeps beam counts low has not been checked. Item pulls have not been seen
reaching the concussion rifle in its alcove from below.

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
