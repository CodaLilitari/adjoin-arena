#!/usr/bin/env bash
cd /workspace/elite-arena-p78/arena-temp
exec /workspace/adjoin-arena-match/venv/bin/python -u -m web_bots.p78_run --data /workspace/jk-data/JK \
  --engine-dir /workspace/elite-arena-p78/engine-temp --p78 /workspace/elite-arena-p78/work/p78-elite-arena/P78.GOB \
  --skin-gob /workspace/elite-arena-p78/temp-skin/TEMP_dlil_skin_from_RedRosterPhoto.gob \
  --runtime /workspace/elite-arena-p78/runs "$@"
