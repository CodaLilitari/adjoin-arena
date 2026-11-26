# Moving saber attacks and vertical aim

The native and JKWeb bots previously discarded their entire movement vector inside 0.16 world units. The competitive saber overlay walks around the opponent at contact and checks the supporting floor before moving. It uses ordinary movement, aim and attack inputs. The production default enables tracking. Set `JK_BOT_SABER_TRACK=0` in a native bot's launch environment to replay the previous behavior on the same binary.

## Controlled comparison

The test starts two player actors 0.14 world units apart on flat ground. Each comparison uses the default tactic table, the same pose and the same attack opportunity. A single process setting selects the behavior. The driver captures ten consecutive 20 ms frames in which the saber trigger is held. A second executable replays those exact inputs from rest through stock multiplayer player movement and ground physics.

| Result after 0.20 game seconds | Previous behavior | Competitive behavior |
| --- | ---: | ---: |
| Frames holding an attack | 10 / 10 | 10 / 10 |
| Attack frames with lateral input | 0 / 10 | 10 / 10 |
| Horizontal displacement, world units | 0 | 0.022630893 |
| Final horizontal speed, world units/s | 0 | 0.20691215 |

The fight dispatcher also vetoed movement when neither side had supporting floor. A target rising or falling relative to the bot produced a pitch request in that direction. Equal vertical velocities produced zero lead on a level target. A target directly above the bot produced positive pitch. The vertical prediction uses 80 ms of relative velocity, bounded by the smaller of the target radius and 0.08 world units.

## Which hitbox the bot sees

The collision test holds the target origin fixed and puts its only collision face first below and then above that origin. In both cases a horizontal ray missed. The tracked ray hit the face with the stock JK world and mesh intersection code. Stock actor pose code pitched the torso and primary weapon joint in the sampled direction. Inserting a closer player blocked both rays.

An ordinary spherical player collider stays centred on the player's thing position. Changing the rendered skin alone does not move that collider. Its rising or falling position still affects aim. A nearby mesh collider receives an origin probe and up to four height samples. If no sample reaches the target, the bot falls back to the collider origin. Very small faces between samples can be missed. In a crowded spot a nearer object can mask a probe. The collision test exercises JK face colliders. The separate MotS sphere-tree path has no animated-model fixture here.

## Reproduce

Run the commands below from the repository root on a GCC-compatible Linux build. Set `SRC` to the assembled native engine source and `BUILD` to its configured Unix Makefiles build directory. The latter supplies `CMakeFiles/sith_engine.dir/flags.make` and `generated/globals.c`. The Red transfer build also requires OpenSSL's development library. Fixtures supply their own synthetic geometry.

```sh
python3 -B native/tests/run_bot_driver_tests.py --source "$SRC" --build "$BUILD"
python3 -B native/tests/run_bot_collision_tests.py --source "$SRC" --build "$BUILD" --saber
python3 -B native/tests/run_stock_ground_tests.py --source "$SRC" --build "$BUILD" --saber
```

The source exercised on 2026-11-26 was the Muse/Wren native client with these additions in order.

1. Apply `native/red-policy.patch` and `native/red-transfer.patch`. Place `native/red_policy.inc`, `native/red_transfer.inc` and `native/red_nav_recall.h` in `src/AI/`, as in the transfer recipe.
2. Apply `native/saber-combat.patch` followed by `native/competitive-light-profile.patch`, as in `native/build_competitive.py`. All four patches applied with `patch --fuzz=0 -p1` to the LF-normalized inputs. Use an external engine build directory.
3. Run the three commands above. The full driver returned 99 passing groups. The collision runner returned four. The focused stock-motion runner returned the driver result and a displacement/speed line for each profile. Running the stock ground suite without `--saber` also passed.

The tested native saber overlay has SHA-256 `b1ecbe1105044cedf72b0151f5e0bae6917b12d21a008780121327d601547482`. The matching JKWeb saber overlay has SHA-256 `7dc46986084f4b399299efaf0e0a75e526a9a074e463c65fc9733fd4c099e72b`. The measurements in the table come from the native fixture. A moving opponent, actual swing keyframes, remote prediction, game-clock hit registration and match outcomes require separate game-session evidence.
