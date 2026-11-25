#!/usr/bin/env bash
# Resume the live 'Wren' JKZone match after a box reboot/reset.
# Recreates the venv if it is gone, stops any stale match processes, then
# starts watchdog.py. The lineup (host, joiners, coach seat, skins, sabers, end
# time) is live/lineup.json, read before every (re)launch; the watchdog hosts
# the room, starts each joiner in its own Chrome, attaches the coach seat, logs
# per-seat game-time rates every minute, and relaunches on any drop.
set -euo pipefail
M=/workspace/adjoin-arena-match; L=$M/live
if [ ! -x $M/venv/bin/python ] || ! $M/venv/bin/python -c 'import aiohttp, playwright' 2>/dev/null; then
  python3 -m venv $M/venv && $M/venv/bin/pip install -q aiohttp playwright cmake ninja
fi
if [ -f $L/PIDS ]; then
  P=$(awk '$1=="watchdog"{print $2}' $L/PIDS)
  if [ -n "$P" ] && kill -0 "$P" 2>/dev/null && grep -q watchdog.py /proc/$P/cmdline 2>/dev/null; then
    echo "watchdog already running (pid $P)"; exit 0; fi
fi
pkill -TERM -f 'bots.coach_seat' 2>/dev/null || true; sleep 1
pkill -INT -f 'web_bots.headless' 2>/dev/null || true; sleep 3
nohup setsid $M/venv/bin/python -u $L/watchdog.py >> $L/watchdog-stdout.log 2>&1 < /dev/null &
echo "watchdog started pid $!  (log: $L/watchdog.log, room: $L/current.json, PIDs: $L/PIDS)"
