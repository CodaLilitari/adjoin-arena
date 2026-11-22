# Stock water replay

Use this Linux fixture to replay an observed swimmer state on an owned Canyon Oasis map. It runs one bot control update per chosen control frame and 150 physics steps per game second. It succeeds after the actor stays attached to a floor in the requested dry sector for 38 consecutive physics steps. Drowning, an unavailable exit edge, or 60 simulated seconds without a supported landing fail the run.

Provide a patched JKWeb engine checkout with its dependency headers, the native CMake build directory used by the other bot tests, and your own extracted Canyon Oasis JKL. The build directory must contain `CMakeFiles/sith_engine.dir/flags.make` and the generated headers referenced by its include paths. Run from the repository root. Set the shell variables below from the observed state, using game units for position and vertical speed, degrees for pitch and yaw, hexadecimal for physics flags, and milliseconds for endurance.

```sh
python3 native/tests/stock_water_replay/run.py \
  --source "$PATCHED_WEB_SOURCE" --build "$NATIVE_BUILD" --map "$OWNED_JKL" \
  --position "$X" "$Y" "$Z" --control-hz "$CONTROL_HZ" \
  --flags "$PHYSICS_FLAGS" --health "$HEALTH" --endurance-ms "$ENDURANCE_MS" \
  --pitch "$PITCH" --yaw "$YAW_OFFSET" --vertical-speed "$VERTICAL_SPEED"
```

The yaw offset rotates the initial heading relative to the wet-to-dry edge. The default Canyon Oasis setup starts the graph builder at spawn sector 41 and selects an exit edge from sector 54 to sector 41. The actor starts at the supplied observation position with zero horizontal velocity. The fixture uses the stock player size, standing height, air drag and thrust. The bot's underwater timer starts at 20 seconds so these cases exercise air recovery; the supplied endurance field governs actual drowning. This fixture does not establish when a fresh dive first selects an air objective.

The runner extracts the required stock control, movement, sector transition and endurance functions from the supplied source checkout. Physics and world collision code come from that checkout as well. The map conversion, generated C include and executable live in a temporary directory. Rendering, sound, inventory powers, multiplayer transport and other players are outside this fixture. The actor begins with the specified health, and the damage callback deducts the stock actor timer's damage directly.

Look for `BREATH` (endurance reset), `TRANSITION` (a sector or surface flag change) and `SUPPORTED_DRY` (sustained floor attachment). The process exit code reports the final result.
