"""Run several JKWeb bot seats with no desktop: join a listed room, or host one.

Each seat is the same bot page as web_bots.join_room, opened in its own
browser context of one headless Chrome (``--display headless``, the default)
or of a Chrome on a private Xvfb display (``--display xvfb``). The seat's
engine credential is injected before navigation, exactly like
web_bots/launch_chrome.py, so no file picker is involved. The launcher serves
the operator's own game files to each seat.

    # N bots into an open listed room
    python -m web_bots.headless join --room-id 42 --seats red,lilivane,biddy \\
        --data "/path/to/Jedi Knight" --runtime runtime/headless

    # one bot hosts a room (12 slots, Canyon Oasis, full Force), the rest join it
    python -m web_bots.headless host --room-name Canyon_Wren --max-players 12 \\
        --host-seat lily --seats red,lilivane,biddy,t800,crownbraid \\
        --relay ws://127.0.0.1:8080/relay --data ... --runtime ...

Hosting on the public Jedi Knight Zone relay lists the room publicly and its
matches reach the public leaderboard, so it also needs --public-room.
Every seat writes its companion credential; ``headless.json`` in the run
directory lists them for bots.coach_seat. Wren (AI collaborator, via Grok Bot).
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
from dataclasses import dataclass
from functools import cached_property
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import subprocess
import time
from types import SimpleNamespace

from aiohttp import web
from web_bots.join_room import ZONE_RELAY, episode_file, join_rules, list_games, relay_url, select_room
from web_bots.serve import ARENA_MODES, HERE, ROOM_PLAYERS, Host

MAX_BOTS = 11
SOFTWARE_GL = ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"]
QUIET = ["--disable-background-timer-throttling", "--disable-renderer-backgrounding",
         "--disable-backgrounding-occluded-windows", "--autoplay-policy=no-user-gesture-required",
         "--mute-audio", "--no-first-run", "--no-default-browser-check"]


@dataclass(frozen=True)
class HostedRoom:
    relay: str
    seat: str
    max_players: int
    level: str
    room: str
    episode: str = "JK1MP"
    episode_file: Path | None = None

    @cached_property
    def content_identity(self):
        from bots.jhs_roof import episode_identity
        return episode_identity(self.episode_file, self.level)

    def public(self):
        return {"relay": self.relay, "seat": self.seat, "max_players": self.max_players,
                "episode": self.episode, "map": self.level, "room": self.room, "netcode": 2, **self.content_identity}


def parse_seats(text, *, host_seat=None, max_players=None):
    seats = [s for s in (text or "").split(",") if s]
    if host_seat is None and not seats:
        raise ValueError("Specify at least one seat.")
    if len(set(seats)) != len(seats):
        raise ValueError("Each seat may appear once.")
    unknown = [s for s in seats if s not in ROOM_PLAYERS]
    if unknown:
        raise ValueError("Unknown seats: " + ", ".join(unknown) + ". Choose from " + ", ".join(ROOM_PLAYERS) + ".")
    if host_seat is not None and host_seat in seats:
        raise ValueError("The host seat is started separately; leave it out of --seats.")
    total = len(seats) + (host_seat is not None)
    if total > MAX_BOTS:
        raise ValueError(f"At most {MAX_BOTS} bots per launcher.")
    if max_players is not None and total > max_players:
        raise ValueError("More bots than the room has player slots.")
    return seats


def find_hosted(games, room_name, max_players):
    hits = [g for g in games if isinstance(g, dict) and g.get("name") == room_name
            and g.get("max") == max_players and type(g.get("id")) is int]
    if len(hits) != 1:
        return None
    return hits[0]["id"]


class Launcher:
    def __init__(self, args):
        self.args, self.hosts, self.runners, self.seats = args, {}, {}, {}
        stamp = time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3)
        self.run = Path(args.runtime).resolve() / ("headless-" + stamp)
        self.run.mkdir(parents=True)
        self.status_log = (self.run / "status.jsonl").open("a", encoding="utf-8")
        self.xvfb = None
        self.started = time.monotonic()
        self.manifest = {"relay": args.relay, "display": args.display, "seats": {}, "started": time.time()}

    def log(self, **fields):
        line = json.dumps(dict(t=round(time.monotonic() - self.started, 1), **fields), sort_keys=True)
        print(line, flush=True)

    def save(self):
        temp = self.run / "headless.json.tmp"
        temp.write_text(json.dumps(self.manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temp, self.run / "headless.json")

    async def add_host(self, ident, host, role):
        runner = web.AppRunner(host.app(), access_log=None, shutdown_timeout=1.)
        await runner.setup()
        await web.TCPSite(runner, "127.0.0.1", 0).start()
        host.set_port(runner.addresses[0][1])
        self.hosts[ident], self.runners[ident] = host, runner
        self.manifest["seats"][ident] = {
            "role": role, "page": host.url + "/bot/" + ident + ("?netlog" if self.args.netlog else ""),
            "status": host.url + "/status",
            "companion_credential": str((host.runtime / "companion" / (ident + ".json")).resolve()),
            "engine_credential": str((host.secrets_dir / (ident + ".json")).resolve()),
            "run": str((host.runtime / "run.json").resolve())}
        self.save()

    async def open_browser(self, pw):
        env = dict(os.environ)
        crashes = self.run / "crashes"
        crashes.mkdir(exist_ok=True)
        env["CHROME_LOG_FILE"] = str(self.run / "chrome.log")
        headless = self.args.display == "headless"
        if not headless:
            if not shutil.which("Xvfb"):
                raise ValueError("--display xvfb needs Xvfb installed.")
            display = ":" + str(self.args.xvfb_display or (90 + os.getpid() % 300))
            self.xvfb = subprocess.Popen(["Xvfb", display, "-screen", "0", "1280x800x24", "-nolisten", "tcp"],
                                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            await asyncio.sleep(1.0)
            env["DISPLAY"] = display
        extra = ["--enable-logging", f"--crash-dumps-dir={crashes}"]
        if self.args.raster_threads > 0:
            extra.append(f"--num-raster-threads={self.args.raster_threads}")
        browser = await pw.chromium.launch(
            executable_path=str(self.args.chrome), headless=headless, env=env,
            args=QUIET + extra + (SOFTWARE_GL if self.args.software_gl else []))
        browser.on("disconnected", lambda: self.log(event="browser_disconnected"))
        return browser

    async def open_seat(self, browser, ident):
        host = self.hosts[ident]
        page_url = self.manifest["seats"][ident]["page"]
        ctx = await browser.new_context(viewport={"width": self.args.width, "height": self.args.height},
                                        device_scale_factor=1)
        page = await ctx.new_page()
        token = host.tokens[ident]
        init_js = ("if(window===top && location.href===" + json.dumps(page_url) +
                   ") window.__JK_BOT_TOKEN=" + json.dumps(token) + ";")
        if self.args.fps_cap > 0:
            min_ms = 1000.0 / self.args.fps_cap
            init_js += (
                "(()=>{const m=" + f"{min_ms:.3f}" + ",o=window.requestAnimationFrame.bind(window);let l=0;"
                "window.requestAnimationFrame=cb=>o(t=>{if(!l||t-l>=m-1){l=t;cb(t);}else{window.requestAnimationFrame(cb);}});})();"
            )
        await page.add_init_script(init_js)
        console = (self.run / (ident + ".console.log")).open("a", encoding="utf-8")
        def note(kind, text):
            text = str(text).replace(token, "[redacted]")
            console.write(f"{time.monotonic()-self.started:8.2f} {kind} {text[:800]}\n"); console.flush()
            if "BOT_WEB_HOST " in text:
                self.seats[ident]["hosted"] = True
            if "BOT_JOIN_REJECTED" in text:
                self.seats[ident]["rejected"] = text[:200]
        page.on("console", lambda m: note(m.type, m.text))
        page.on("pageerror", lambda e: note("pageerror", e))
        page.on("crash", lambda: (note("crash", "page crashed"), self.seats[ident].update(crashed=True)))
        page.on("close", lambda: (note("close", "page closed"), self.seats[ident].update(closed=True)))
        self.seats[ident] = {"ctx": ctx, "page": page, "hosted": False, "rejected": None, "crashed": False, "closed": False}
        await page.goto(page_url, wait_until="domcontentloaded", timeout=30000)

    def seat_status(self, ident):
        host = self.hosts[ident]
        host.hub.pump()
        with host.hub.lock:
            bot = host.hub.bots[ident]
            state = bot.state or {}
            fresh = bot.state is not None and host.hub.clock() - bot.observed <= 3
        seat = host.seats[ident]
        return {"joined": bool(fresh), "stage": seat["stage"], "kills": state.get("kills"),
                "deaths": state.get("deaths"), "health": state.get("health"),
                "renderer": (seat.get("graphics") or {}).get("renderer"),
                "navigation_discarded": seat["nav_dropped"]}

    async def wait_joined(self, ident, timeout):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            status = self.seat_status(ident)
            if status["joined"]:
                return True
            if status["stage"] == "failed" or self.seats[ident].get("rejected"):
                return False
            await asyncio.sleep(0.5)
        return False

    async def pump(self, until, *, browser=None, watch_seat=None, drop_grace=20.0):
        next_status = 0
        dropped_since = None
        while time.monotonic() < until:
            for host in self.hosts.values():
                host.hub.pump()
                host.expire_capture()
            if browser is not None and not browser.is_connected():
                self.log(event="abort", reason="browser_disconnected")
                raise RuntimeError("Chrome browser disconnected.")
            if watch_seat and watch_seat in self.seats:
                s = self.seats[watch_seat]
                if s.get("crashed") or s.get("closed"):
                    self.log(event="abort", reason="watch_seat_crashed", seat=watch_seat)
                    raise RuntimeError(f"Seat {watch_seat} crashed or closed.")
            if time.monotonic() >= next_status:
                next_status = time.monotonic() + 5
                row = {ident: self.seat_status(ident) for ident in self.hosts}
                self.status_log.write(json.dumps({"t": round(time.monotonic() - self.started, 1), "seats": row}) + "\n")
                self.status_log.flush()
                if watch_seat and watch_seat in row:
                    if row[watch_seat]["joined"]:
                        dropped_since = None
                    else:
                        dropped_since = dropped_since or time.monotonic()
                        if time.monotonic() - dropped_since >= drop_grace:
                            self.log(event="abort", reason="watch_seat_dropped", seat=watch_seat)
                            raise RuntimeError(f"Seat {watch_seat} stopped reporting state for {drop_grace:.0f}s.")
            await asyncio.sleep(0.05)

    async def join_seats(self, browser, room_id, seats):
        games = await list_games(self.args.relay)
        results = {}
        rules = (self.args.mode, True) if self.args.command == "host" else None
        for ident in seats:
            spec = SimpleNamespace(data=self.args.data, room_id=room_id, seat=ident, relay=self.args.relay,
                                   episode_gob=self.args.episode_gob, allow_mod=self.args.model_gob is not None)
            room = select_room(games, spec)
            if rules is None:
                rules = await join_rules(room, self.args.sabers_only)
            host = Host(self.args.data, self.args.engine_dir, self.run / ident, str(room_id), self.args.model_gob, self.args.companion_chat,
                        rules[0], learn_navigation=rules[1],
                        adaptive_lily=self.args.adaptive_lily and ident == "lily", external=room,
                        red_sabers=self.args.red_sabers, taunts=not self.args.no_taunts)
            await self.add_host(ident, host, "join")
            await self.open_seat(browser, ident)
            ok = await self.wait_joined(ident, self.args.join_timeout)
            results[ident] = ok
            self.manifest["seats"][ident]["joined"] = ok
            self.save()
            self.log(event="seat", seat=ident, joined=ok, rejected=self.seats[ident].get("rejected"))
            if ok:
                games = await list_games(self.args.relay)  # the next seat checks the updated slot count
        return results

    async def main(self):
        from playwright.async_api import async_playwright
        a = self.args
        self.log(event="run", dir=str(self.run), relay=a.relay, display=a.display)
        async with async_playwright() as pw:
            browser = await self.open_browser(pw)
            try:
                if a.command == "host":
                    archive = episode_file(a.data, a.episode, a.map, a.episode_gob)
                    hosted = HostedRoom(a.relay, a.host_seat, a.max_players, a.map, a.room_name, a.episode, archive)
                    host = Host(a.data, a.engine_dir, self.run / a.host_seat, a.room_name, a.model_gob, a.companion_chat, a.mode,
                                adaptive_lily=a.adaptive_lily and a.host_seat == "lily", hosted=hosted,
                                red_sabers=a.red_sabers, taunts=not a.no_taunts, private_duels=a.private_duels)
                    self.manifest["hosted"] = hosted.public()
                    await self.add_host(a.host_seat, host, "host")
                    await self.open_seat(browser, a.host_seat)
                    ok = await self.wait_joined(a.host_seat, a.join_timeout)
                    room_id = None
                    deadline = time.monotonic() + 30
                    while ok and room_id is None and time.monotonic() < deadline:
                        room_id = find_hosted(await list_games(a.relay), a.room_name, a.max_players)
                        if room_id is None:
                            await asyncio.sleep(1)
                    self.manifest["room_id"] = room_id
                    self.manifest["seats"][a.host_seat]["joined"] = ok
                    self.save()
                    self.log(event="hosted", seat=a.host_seat, joined=ok, room_id=room_id,
                             max_players=a.max_players, map=a.map, mode=a.mode)
                    if not ok or room_id is None:
                        raise RuntimeError("The host seat did not open a listed room.")
                else:
                    room_id = a.room_id
                    self.manifest["room_id"] = room_id
                await self.join_seats(browser, room_id, a.seat_list)
                self.log(event="playing", seconds=a.seconds, manifest=str(self.run / "headless.json"))
                watch = (a.host_seat if a.command == "host" else None) if a.exit_on_drop else None
                await self.pump(time.monotonic() + a.seconds, browser=browser, watch_seat=watch)
                for ident, seat in self.seats.items():
                    with contextlib.suppress(Exception):
                        await seat["page"].screenshot(path=str(self.run / (ident + "-final.png")), timeout=5000)
            finally:
                for seat in self.seats.values():
                    with contextlib.suppress(Exception):
                        await seat["ctx"].close()   # closing the page = the bot leaves the game
                with contextlib.suppress(Exception):
                    await browser.close()

    async def close(self):
        final = {ident: self.seat_status(ident) for ident in self.hosts}
        self.manifest["final"] = final
        self.save()
        for ident, runner in self.runners.items():
            with contextlib.suppress(Exception):
                await runner.cleanup()
            self.hosts[ident].close()
        if self.xvfb:
            self.xvfb.terminate()
        self.status_log.close()


def build_parser():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="command", required=True)
    join = sub.add_parser("join", help="Add bot seats to an open listed room.")
    host = sub.add_parser("host", help="One bot hosts a room; the other seats join it.")
    for c in (join, host):
        c.add_argument("--relay", default=ZONE_RELAY)
        c.add_argument("--seats", required=True, help="Comma-separated joining seats, e.g. red,lilivane,biddy.")
        c.add_argument("--data", type=Path, required=True)
        c.add_argument("--runtime", type=Path, required=True)
        c.add_argument("--engine-dir", type=Path, default=HERE.parent / "bin/bots-jkweb")
        c.add_argument("--episode-gob", type=Path)
        c.add_argument("--adaptive-lily", action="store_true")
        c.add_argument("--seconds", type=float, default=600)
        c.add_argument("--join-timeout", type=float, default=180)
        c.add_argument("--display", choices=("headless", "xvfb"), default="headless")
        c.add_argument("--xvfb-display", type=int)
        c.add_argument("--chrome", type=Path, default=Path(shutil.which("google-chrome") or "/usr/bin/google-chrome"))
        c.add_argument("--software-gl", action=argparse.BooleanOptionalAction, default=True,
                       help="Render WebGL through SwiftShader (default; no GPU needed).")
        c.add_argument("--width", type=int, default=480)
        c.add_argument("--height", type=int, default=300)
        c.add_argument("--netlog", action="store_true",
                       help="Open seats with ?netlog: every engine network-log line goes to the console log.")
        c.add_argument("--fps-cap", type=float, default=0.0, help="Throttle requestAnimationFrame to N fps (0 = uncapped).")
        c.add_argument("--raster-threads", type=int, default=0, help="Chromium --num-raster-threads (0 = default).")
        c.add_argument("--exit-on-drop", action=argparse.BooleanOptionalAction, default=True,
                       help="Exit non-zero if Chrome disconnects or the host seat crashes/drops.")
        c.add_argument("--companion-chat", action="store_true", help="Allow an attached local coach to reply in public game chat.")
        c.add_argument("--no-taunts", action="store_true", help="Silence automatic character lines.")
        c.add_argument("--model-gob", type=Path,
                       help="A -path mod GOB loaded by every seat (jkmods/companion); seats whose roster body it "
                            "carries wear it. The host's JKWeb shares it with joiners and spectators in-game.")
        c.add_argument("--red-sabers", type=lambda t: tuple(x for x in t.split(",") if x), default=("lily",),
                       help="Comma-separated seats with a red saber (saberred1/0.mat); the rest are green.")
    join.add_argument("--room-id", type=int, required=True)
    join.add_argument("--sabers-only", action="store_true")
    host.add_argument("--room-name", default="Canyon_" + secrets.token_hex(3))
    host.add_argument("--host-seat", default="lily", choices=tuple(ROOM_PLAYERS))
    host.add_argument("--max-players", type=int, default=12)
    host.add_argument("--episode", help="Host JK1MP, JK1CTF, or the basename of a locally owned episode GOB.")
    host.add_argument("--map", help="JKL inside the episode. Defaults to m10.jkl in JK1MP or c1.jkl in JK1CTF.")
    host.add_argument("--mode", choices=ARENA_MODES, default="ff-guns", help="ff-guns hosts Jedi rank 8 (full Force).")
    host.add_argument("--private-duels", action="store_true", help="Allow ordinary JKWeb saber challenges in this hosted free-for-all.")
    host.add_argument("--public-room", action="store_true",
                      help="Required to host on the public Jedi Knight Zone relay (listed, on its leaderboard).")
    return p


def validate(args, parser):
    try:
        relay_url(args.relay)
        if args.command == "host":
            if args.relay == ZONE_RELAY and not args.public_room:
                raise ValueError("Hosting on the public Jedi Knight Zone relay lists the room publicly and "
                                 "reports matches to its leaderboard. Add --public-room to confirm.")
            if not 2 <= args.max_players <= 16:
                raise ValueError("--max-players must be 2..16.")
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,31}", args.room_name):
                raise ValueError("--room-name: 1..31 letters, digits, _ or -.")
            args.episode = args.episode or (args.episode_gob.stem if args.episode_gob else "JK1MP")
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,31}", args.episode):
                raise ValueError("--episode must be a GOB basename, such as JK1CTF.")
            args.map = args.map or {"jk1mp": "m10.jkl", "jk1ctf": "c1.jkl"}.get(args.episode.casefold())
            if not args.map or not re.fullmatch(r"[A-Za-z0-9_-]{1,26}\.jkl", args.map):
                raise ValueError("--map must identify a JKL inside the selected episode.")
            args.seat_list = parse_seats(args.seats, host_seat=args.host_seat, max_players=args.max_players)
        else:
            args.seat_list = parse_seats(args.seats)
        if args.adaptive_lily and "lily" not in args.seat_list + ([args.host_seat] if args.command == "host" else []):
            raise ValueError("--adaptive-lily needs the lily seat.")
    except ValueError as error:
        parser.error(str(error))


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    validate(args, parser)
    async def run():
        launcher = Launcher(args)
        loop = asyncio.get_running_loop()
        task = asyncio.current_task()
        for sig in (signal.SIGINT, signal.SIGTERM):
            with contextlib.suppress(NotImplementedError):
                loop.add_signal_handler(sig, task.cancel)
        try:
            await launcher.main()
        finally:
            await launcher.close()
    try:
        asyncio.run(run())
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    except (OSError, ValueError, RuntimeError, TimeoutError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
