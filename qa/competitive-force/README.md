# Native competitive Force observation

`harness.py` runs a bounded stock `JK1MP/m2.jkl` rank-eight session with the
packaged dedicated server and two ordinary competitive bot clients. Supply
the repository, owned game-data directory, and a new output directory as
`--repo`, `--data`, and `--output`; `--duration` accepts 1 through 120 seconds
after both clients join.

Run it in a private Linux network namespace with loopback enabled. The native
GNS server normally binds all interfaces, so merely connecting the bots to
127.0.0.1 does not isolate the listener. The qualification runner used a new
unprivileged user/network namespace and verified that loopback was its only
network interface. No browser gateway or public server listing is involved.

The harness uses the Python standard library, the checked-in repository
modules, and ordinary native runtime dependencies. It requires software
EGL/OpenGL but no Xvfb or Python networking package. It verifies the packaged
bot binary, GNS library, source patch, original multiplayer GOB, and selected
JKL hashes before play. Only private copies of the four necessary stock input
files are staged. Original archives are opened read-only. No controls, stars,
inventory, effects or positions are written directly into the running game.

The complete budget is 180 seconds, including startup and cleanup. The process
groups owned by this run are stopped on completion, error or a handled signal.
Staged game inputs and isolated player profiles are removed. Raw process logs
remain in the new output directory for private debugging; publish only the
numeric receipt and selected, reviewed trace evidence.

Exit zero establishes distinct native joins and matching live star vectors.
The receipt separates requested inputs from sampled active bins, mana changes,
health changes and immobility. It does not attribute damage or immobility to a
particular caster, prove a short effect was absent between samples, establish
current JKWeb interoperability, or measure strength against humans. The
packaged `BOT_FORCE_STATE` trace samples only each bot's own state.
