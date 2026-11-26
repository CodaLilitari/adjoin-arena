# Battleground Jedi shallow-water movement

On November 26, 2026, four bots in JKZone room 1170 repeatedly stood or jumped in place along the stream. BGJ marks its solid streambed as a water surface. At the sector 29 spawn, the player's origin stays in air while its feet rest on the bed. Both the floor probe and the run-up check rejected that support. The JKWeb movement controller now measures the water depth and checks the slope, footing, standing position and path ahead before walking or strafe-running.

## Same spawn, normal game clock

The private single-bot drill placed the multiplayer starts on the existing sector 29 spawn. It used stock geometry, fresh navigation memory and no opponent or coach. The exit time is the beginning of at least 0.8 continuous game seconds of supported movement off the bed, within the same life.

| 65-second drill | Previous build | Corrected build |
|---|---:|---:|
| Sustained exit from the bed | Stayed for the full drill | 2.38 game seconds |
| Sectors visited | 1 | 10 |
| Maximum horizontal distance from spawn, in world units | 0.038 | 4.619 |
| Boosted diagonal running in six complete movement reports | 0.0 seconds | 2.5 seconds |

A separate 35-second run from the same spawn produced another full-duration stall on the previous build. The corrected bot exited in 2.37 game seconds. There were no deaths in these four drills.

## Six-bot NF sabers on the stock map

The comparison uses 130 wall seconds of the original public game and 130 wall seconds of a private loopback game with the corrected engine, the same six R3 models and the default run thresholds. Both games used `JK1MP/m_boss17.jkl` at normal speed. Combat, spawns and crowding varied between the two games.

| Measurement, all six bots | Public game before fix | Private game after fix |
|---|---:|---:|
| Ten-second observation windows with enough samples | 73 | 78 |
| Windows primarily over the streambed, excluding death transitions | 33 | 6 |
| Of those, windows stationary on the bed | 31 | 0 |
| Alive time covered by complete engine movement reports | 621.0 bot-seconds | 620.9 bot-seconds |
| Running | 106.7 bot-seconds | 189.2 bot-seconds |
| Boosted diagonal running | 33.0 bot-seconds | 96.1 bot-seconds |

One observation window follows one bot. At least eight position samples spanning seven seconds were required. A stationary bed window had at least half its samples over a measured bed face and at most 0.10 world units between any two horizontal positions. Run times come from complete engine reports and sum across bots. Every corrected bot recorded boosted diagonal running, ranging from 8.2 to 20.9 seconds. These runs qualify the reported BGJ streambed case.

| Tested artifact | SHA-256 |
|---|---|
| Previous JKWeb WASM | `ba49673726ef819ad0d2b54b30f0ea9fbdebb5b7136b697e42f0a382be85d11c` |
| Corrected JKWeb WASM | `09173ae997b43d339959692b0df387611ec4caa1aa3166cf70392d8ffb28f643` |
| Stock BGJ JKL | `5c0795709ff3f2da525d0ad9ce4a3e41b13445febc1b5f88f727c864b606349f` |

[Movement patch](../web_bots/shallow-wading.patch) · [JKWeb build manifest](../web_bots/BUILD.json) · [Original public match](https://jediknight.zone/match/71)
