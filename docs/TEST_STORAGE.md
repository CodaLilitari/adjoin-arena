# Storage for native bot matches

To keep repeated games off a space-constrained system disk, set `ADJOIN_MATCH_SCRATCH` to an existing absolute Linux directory on a volume with room for the game files. The native launcher and observation harness also accept `--scratch-root`, which overrides the environment setting. The stock map matrix inherits the environment for each game.

For example, on a Linux host with enough free shared memory:

```sh
df -h /dev/shm
install -d -m 700 "/dev/shm/adjoin-$(id -u)"
export ADJOIN_MATCH_SCRATCH="/dev/shm/adjoin-$(id -u)"
python3 -m bots.run --server-config /path/to/server.json --profiles jan_ors,boba_fett \
    --runtime /path/to/retained-runs --seconds 120
```

An external Linux filesystem such as ext4 can use the same setup with a different path. Allow enough space for the eligible `resource` and `episode` files once per simultaneous match, plus any recording frames or temporary builds. Filesystems without hard-link support need room for seat copies too. A small default `/dev/shm` may be insufficient. For a replay that compiles and launches a temporary test client, choose a mount that permits executing files.

The launcher copies the installed game inputs into one private baseline per match. Each seat normally hard-links its game files from that baseline. Profiles, controls and mutable runtime files have their own directories. The Linux filesystem must support mode `0700` on the fresh match directory. Keep the scratch root outside the checkout, installed game data and retained match output.

The session receipt, per-seat `client.log`, persona, profile and behavior files remain under `--runtime`. With an explicit scratch root, `session.json` records each durable seat path under `directory` and the temporary working path under `engine_directory`. Learning banks use the configured navigation-memory location independently of scratch. The observation harness keeps its receipts, logs and completed recordings in `--output`. The Windows force bridge accepts `--scratch-root` as a path inside its selected WSL distribution.

Normal teardown, handled termination and startup failures remove the match's private input copies. A host crash or uncatchable process kill can leave an owned `jk-force-*` directory behind. Before removing an interrupted run, identify the exact directory and verify that its processes have exited.
