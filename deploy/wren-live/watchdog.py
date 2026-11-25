#!/usr/bin/env python3
"""Watchdog + resource monitor for the live JKZone 'Wren' match + coach seat.

The lineup comes from live/lineup.json, read again before every (re)launch, so a
restart never brings back a lineup that was changed meanwhile. Each joiner runs in
its own Chrome at normal priority, and every minute the watchdog logs each seat's
game-time rate (bot clock / wall clock) from its console log. Wren (AI collaborator, via Grok Bot)."""
from __future__ import annotations

import asyncio
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

REPO = Path("/workspace/adjoin-arena-pr4")
VENV_PY = "/workspace/adjoin-arena-match/venv/bin/python"
DATA_DIR = "/workspace/jk-data/JK"
WASM_PATH = str((REPO / "bin/bots-jkweb/openjkdf2.wasm").resolve())
LIVE = Path("/workspace/adjoin-arena-match/live")
RUNS = LIVE / "runs"
LINEUP = LIVE / "lineup.json"
PIDS_FILE = LIVE / "PIDS"
WATCHDOG_LOG = LIVE / "watchdog.log"
RESOURCES_LOG = LIVE / "resources.log"
CURRENT_JSON = LIVE / "current.json"
RELAY = "wss://jediknight.zone/relay"

sys.path.insert(0, str(REPO))
from web_bots.join_room import list_games  # noqa: E402

STOP = False


def ts():
    return time.strftime("%Y-%m-%d %H:%M:%S %Z")


def wlog(msg):
    line = f"[{ts()}] {msg}"
    with WATCHDOG_LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(line, flush=True)


def kill_proc(proc, sig, wait_s=6):
    if proc is None or proc.poll() is not None:
        return
    try:
        os.killpg(os.getpgid(proc.pid), sig)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + wait_s
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return
        time.sleep(0.25)
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except ProcessLookupError:
        pass


def lineup():
    return json.loads(LINEUP.read_text(encoding="utf-8"))


def coach_dir(cfg):
    return LIVE / ("coach-" + cfg["coach_seat"])


def update_pids(host_proc, joins, coach_proc, cfg=None):
    lines = [f"watchdog {os.getpid()}"]
    if host_proc and host_proc.poll() is None:
        lines.append(f"host_launcher_{cfg['host_seat'] if cfg else 'host'} {host_proc.pid}")
    for seat, (proc, _run) in (joins or {}).items():
        if proc and proc.poll() is None:
            lines.append(f"join_launcher_{seat} {proc.pid}")
    if coach_proc and coach_proc.poll() is None:
        lines.append(f"coach_seat_{cfg['coach_seat'] if cfg else 'seat'} {coach_proc.pid}")
    # Include Chrome browser processes parented by host/join launchers
    try:
        out = subprocess.check_output(
            ["ps", "-eo", "pid,ppid,comm"], text=True, stderr=subprocess.DEVNULL
        )
        roles = {host_proc.pid: "host_chrome"} if host_proc and host_proc.poll() is None else {}
        for seat, (proc, _run) in (joins or {}).items():
            if proc and proc.poll() is None:
                roles[proc.pid] = f"join_chrome_{seat}"
        for row in out.splitlines()[1:]:
            parts = row.split()
            if len(parts) >= 3 and parts[2] == "chrome":
                pid, ppid = int(parts[0]), int(parts[1])
                if ppid in roles:
                    lines.append(f"{roles[ppid]} {pid}")
    except Exception:
        pass
    PIDS_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def sample_resources():
    try:
        ps_out = subprocess.check_output(
            ["ps", "-eo", "pid,ppid,ni,pcpu,pmem,rss,vsz,comm"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
        interesting = [
            l for l in ps_out.splitlines()[1:]
            if any(k in l for k in ("chrome", "python"))
        ]
        mem = subprocess.check_output(["free", "-m"], text=True, stderr=subprocess.DEVNULL).splitlines()
        mem_line = mem[1] if len(mem) > 1 else ""
        with RESOURCES_LOG.open("a", encoding="utf-8") as f:
            f.write(f"=== {ts()} | {mem_line} ===\n")
            for l in interesting:
                f.write(l + "\n")
    except Exception as e:
        wlog(f"resource sample error: {e}")


def dump_crash_evidence(host_run: Path | None, joins: dict | None):
    for label, rdir in [("host", host_run)] + [(f"join-{s}", r) for s, (_p, r) in (joins or {}).items()]:
        if not rdir or not rdir.exists():
            continue
        crashes = list((rdir / "crashes").glob("*")) if (rdir / "crashes").exists() else []
        wlog(f"evidence[{label}] dir={rdir.name} crash_dumps={[c.name for c in crashes]}")
        clog = rdir / "chrome.log"
        if clog.exists():
            tail = clog.read_text(encoding="utf-8", errors="replace").splitlines()[-15:]
            wlog(f"evidence[{label}] chrome.log tail:\n  " + "\n  ".join(tail))
        for console in sorted(rdir.glob("*.console.log")):
            tail = console.read_text(encoding="utf-8", errors="replace").splitlines()[-5:]
            wlog(f"evidence[{label}] {console.name} tail:\n  " + "\n  ".join(tail))


def wait_jsonl_event(log_path: Path, event_name: str, proc: subprocess.Popen, timeout_s: float):
    deadline = time.monotonic() + timeout_s
    seen_dir = None
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return None, seen_dir
        if log_path.exists():
            for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                if ev.get("event") == "run":
                    seen_dir = Path(ev["dir"])
                if ev.get("event") == event_name:
                    return ev, seen_dir
        time.sleep(0.5)
    return None, seen_dir


def start_coach(join_run: Path, attempt: int, seconds: int, cfg: dict):
    COACH_DIR = coach_dir(cfg)
    COACH_DIR.mkdir(parents=True, exist_ok=True)
    coach_log = (COACH_DIR / "coach.log").open("a", encoding="utf-8")
    coach_log.write(f"\n=== [{ts()}] coach attach attempt={attempt} run={join_run.name} ===\n")
    coach_log.flush()
    cmd = [
        VENV_PY, "-u", "-m", "bots.coach_seat",
        "--run", str(join_run / "headless.json"),
        "--seat", cfg["coach_seat"],
        "--dwell-seconds", "90",
        "--memory", str(COACH_DIR / "memory.json"),
        "--label", "jkzone-canyon",
        "--engine", WASM_PATH,
        "--seconds", str(seconds),
        "--control", str(COACH_DIR),
    ]
    return subprocess.Popen(
        cmd, cwd=str(REPO), stdout=coach_log, stderr=subprocess.STDOUT,
        start_new_session=True,
    )


RATE_RE = None


def seat_rates(run_dirs, window=180.0):
    """{seat: (rate, dt_median)} from BOT_* console lines: bot clock (t=) over wall clock, last `window` s."""
    import re, statistics
    global RATE_RE
    RATE_RE = RATE_RE or re.compile(r"^\s*([0-9.]+) \w+ .*?\bt=([0-9.]+)")
    out = {}
    for rdir in run_dirs:
        if not rdir:
            continue
        for console in Path(rdir).glob("*.console.log"):
            text = console.read_text(encoding="utf-8", errors="replace")
            pairs = [(float(m[1]), float(m[2])) for m in map(RATE_RE.match, text.splitlines()) if m]
            dts = [float(x) for x in re.findall(r"BOT_STATUS .*? dt=([0-9.]+)", text)[-10:]]
            if len(pairs) < 2:
                continue
            w1, g1 = pairs[-1]
            w0, g0 = next(p for p in pairs if p[0] >= w1 - window)
            if w1 - w0 >= 30:
                out[console.name.split(".")[0]] = ((g1 - g0) / (w1 - w0), statistics.median(dts) if dts else None)
    return out


def headless_cmd(cfg, command, seats, view, seconds, extra):
    cmd = [VENV_PY, "-u", "-m", "web_bots.headless", command, "--relay", RELAY,
           "--data", DATA_DIR, "--runtime", str(RUNS), "--seats", seats,
           "--width", str(view[0]), "--height", str(view[1]), "--fps-cap", str(view[2]),
           "--raster-threads", "1", "--netlog", "--seconds", str(seconds), "--join-timeout", "180",
           "--red-sabers", cfg.get("red_sabers", "lily")]
    if cfg.get("model_gob"):
        cmd += ["--model-gob", cfg["model_gob"]]
    return cmd + extra


def launch_stack(attempt: int, seconds: int):
    cfg = lineup()
    host_log = LIVE / f"host-{attempt}.log"
    host_f = host_log.open("w", encoding="utf-8")
    host_cmd = headless_cmd(cfg, "host", "", cfg["host_view"], seconds, [
        "--public-room", "--room-name", cfg["room_name"], "--max-players", str(cfg["max_players"]),
        "--map", cfg["map"], "--mode", cfg["mode"], "--host-seat", cfg["host_seat"]])
    wlog(f"attempt={attempt}: lineup host={cfg['host_seat']} joiners={cfg['joiners']} coach={cfg['coach_seat']} "
         f"max={cfg['max_players']} skins={'on' if cfg.get('model_gob') else 'off'} red_sabers={cfg.get('red_sabers')}")
    host_proc = subprocess.Popen(host_cmd, cwd=str(REPO), stdout=host_f, stderr=subprocess.STDOUT,
                                 start_new_session=True)
    ev, host_run = wait_jsonl_event(host_log, "hosted", host_proc, 120)
    if not ev or not ev.get("joined") or not ev.get("room_id"):
        wlog(f"attempt={attempt}: host failed to open room (ev={ev})")
        kill_proc(host_proc, signal.SIGINT)
        return None
    room_id = ev["room_id"]
    wlog(f"attempt={attempt}: room_id={room_id} hosted (dir={host_run})")
    joins = {}
    nice = int(cfg.get("join_nice", 0))
    for seat in cfg["joiners"]:
        log = LIVE / f"join-{attempt}-{seat}.log"
        proc = subprocess.Popen(
            headless_cmd(cfg, "join", seat, cfg["join_view"], seconds, ["--room-id", str(room_id)]),
            cwd=str(REPO), stdout=log.open("w", encoding="utf-8"), stderr=subprocess.STDOUT,
            start_new_session=True, preexec_fn=(lambda: os.nice(nice)) if nice else None)
        jev, run = wait_jsonl_event(log, "playing", proc, 200)
        joins[seat] = (proc, run)
        if not jev or not run:
            wlog(f"attempt={attempt}: joiner {seat} failed to enter playing state (jev={jev})")
            for p, _r in joins.values():
                kill_proc(p, signal.SIGINT)
            kill_proc(host_proc, signal.SIGINT)
            return None
        wlog(f"attempt={attempt}: {seat} joined in its own Chrome (nice {nice}, dir={run})")
    coach_proc = start_coach(joins[cfg["coach_seat"]][1], attempt, seconds, cfg)
    update_pids(host_proc, joins, coach_proc, cfg)
    CURRENT_JSON.write_text(json.dumps({
        "attempt": attempt, "room_id": room_id, "room_name": cfg["room_name"], "lineup": cfg,
        "host_run": str(host_run), "join_runs": {s: str(r) for s, (_p, r) in joins.items()},
        "coach_dir": str(coach_dir(cfg)), "started_at": ts(),
    }, indent=2) + "\n", encoding="utf-8")
    wlog(f"attempt={attempt}: LIVE room_id={room_id} {1 + len(joins)} engines + coach_seat on {cfg['coach_seat']}")
    return room_id, host_proc, joins, coach_proc, host_run, cfg


def check_room_listed(room_id: int) -> tuple[bool, int | None]:
    try:
        games = asyncio.run(list_games(RELAY))
    except Exception as e:
        wlog(f"lobby check error (transient): {e}")
        return True, None  # don't kill on transient lobby WS error
    for g in games:
        if g.get("id") == room_id:
            if not g.get("feed"):
                wlog(f"room_id={room_id} listed but lobby reports feed off")
            return True, g.get("players", 0)
    return False, 0


def main():
    global STOP
    RUNS.mkdir(parents=True, exist_ok=True)
    LIVE.mkdir(parents=True, exist_ok=True)

    def handle_sig(signum, frame):
        global STOP
        STOP = True
    signal.signal(signal.SIGTERM, handle_sig)
    signal.signal(signal.SIGINT, handle_sig)

    # Absolute end (local time, default 16:35) so a resume after a reboot keeps the same plan.
    until = os.environ.get("WATCHDOG_UNTIL") or lineup().get("until", "16:35")
    hh, mm = map(int, until.split(":"))
    lt = time.localtime()
    end_epoch = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, hh, mm, 0, 0, 0, -1))
    end_time = time.monotonic() + max(0, end_epoch - time.time())
    wlog(f"running until {until} local ({int(end_epoch - time.time())} s)")
    attempt = 0
    wlog("watchdog started")

    while not STOP and time.monotonic() < end_time:
        attempt += 1
        remaining = max(600, int(end_time - time.monotonic()) + 120)
        launched = launch_stack(attempt, remaining)
        if not launched:
            wlog(f"attempt={attempt}: retrying in 5s")
            time.sleep(5)
            continue
        room_id, host_proc, joins, coach_proc, host_run, cfg = launched
        last_rate = time.monotonic()
        missing_streak = 0
        last_lobby = time.monotonic()
        last_sample = 0.0

        while not STOP and time.monotonic() < end_time:
            now = time.monotonic()
            if now - last_sample >= 15:
                sample_resources()
                update_pids(host_proc, joins, coach_proc, cfg)
                last_sample = now
            if now - last_rate >= 60:
                last_rate = now
                rates = seat_rates([host_run] + [r for _p, r in joins.values()])
                wlog("rates " + " ".join(f"{s}={r:.2f}(dt {d if d is None else round(d, 3)})"
                                         for s, (r, d) in sorted(rates.items())))
                slow = [s for s, (r, _d) in rates.items() if r < 0.9]
                if slow:
                    wlog(f"WARN below real time: {slow}")

            if host_proc.poll() is not None:
                wlog(f"HOST EXITED rc={host_proc.returncode} (room_id={room_id}); restarting")
                dump_crash_evidence(host_run, joins)
                break

            dead = [s for s, (p, _r) in joins.items() if p.poll() is not None]
            if dead:
                wlog(f"JOINER(S) EXITED {dead} (room_id={room_id}); restarting room cleanly")
                dump_crash_evidence(host_run, joins)
                break

            if coach_proc.poll() is not None:
                wlog(f"coach_seat exited rc={coach_proc.returncode}; reattaching to {cfg['coach_seat']}")
                coach_proc = start_coach(joins[cfg["coach_seat"]][1], attempt, remaining, cfg)
                update_pids(host_proc, joins, coach_proc, cfg)

            if now - last_lobby >= 30:
                last_lobby = now
                listed, players = check_room_listed(room_id)
                if not listed:
                    missing_streak += 1
                    wlog(f"room_id={room_id} missing from lobby ({missing_streak}/3)")
                    if missing_streak >= 3:
                        wlog(f"room_id={room_id} confirmed unlisted; restarting")
                        dump_crash_evidence(host_run, joins)
                        break
                else:
                    missing_streak = 0

            time.sleep(3)

        # Clean teardown of current attempt
        kill_proc(coach_proc, signal.SIGTERM, wait_s=4)
        for p, _r in joins.values():
            kill_proc(p, signal.SIGINT, wait_s=6)
        kill_proc(host_proc, signal.SIGINT, wait_s=6)
        if not STOP and time.monotonic() < end_time:
            time.sleep(4)

    wlog("watchdog exiting cleanly")


if __name__ == "__main__":
    main()
