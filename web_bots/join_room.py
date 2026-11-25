"""List JKWeb games and connect one bot to an operator-selected ordinary player slot."""
from __future__ import annotations

import argparse
import asyncio
import base64
import binascii
from dataclasses import dataclass
import json
from pathlib import Path
import re
import secrets
import time
from urllib.parse import urlsplit

from aiohttp import ClientSession, WSMsgType, web
from manager.content import archive_index
from web_bots.serve import HERE, ROOM_PLAYERS, Host, game_file

ZONE_RELAY = "wss://jediknight.zone/relay"


def relay_url(value):
    """Accept the official game service or an explicitly selected local replica."""
    if value == ZONE_RELAY:
        return value
    parsed = urlsplit(value)
    if (parsed.scheme == "ws" and parsed.hostname == "127.0.0.1" and parsed.port
            and value == f"ws://127.0.0.1:{parsed.port}/relay"):
        return value
    raise ValueError("Choose the official Jedi Knight Zone relay or ws://127.0.0.1:PORT/relay.")


async def list_games(url):
    async with asyncio.timeout(12), ClientSession() as client:
        async with client.ws_connect(relay_url(url), max_msg_size=512*1024, compress=0) as ws:
            # The same read-only counts subscription as the official landing page.
            await ws.send_str("watch")
            async for msg in ws:
                if msg.type != WSMsgType.TEXT:
                    raise ValueError("Lobby closed before returning its room list.")
                if msg.data.startswith("status "):
                    value = json.loads(base64.b64decode(msg.data[7:], validate=True))
                    if not isinstance(value, dict) or not isinstance(value.get("games"), list):
                        raise ValueError("Malformed lobby status.")
                    return value["games"]
                if msg.data.startswith("error "):
                    raise ValueError("Lobby declined the status subscription.")
    raise ValueError("Lobby returned no room status.")


@dataclass(frozen=True)
class SelectedRoom:
    relay: str
    room_id: int
    episode: str
    level: str
    seat: str
    episode_file: Path | None

    def public(self):
        return {"relay":self.relay, "id":self.room_id, "episode":self.episode,
                "map":self.level, "seat":self.seat, "netcode":2}


def unsupported(game, allow_mod=False):
    if game.get("game") != "jk1" or game.get("net") != 2:
        return "requires full Jedi Knight on WSRelay netcode 2"
    if game.get("locked") is not False:
        return "password required"
    if game.get("mod") and not allow_mod:
        return "requires a host mod"
    if type(game.get("players")) != int or type(game.get("max")) != int or not 0 < game["players"] < game["max"]:
        return "no open player slot"
    episode = game.get("episode", "")
    level = game.get("map", "")
    if not (isinstance(episode, str) and isinstance(level, str) and
            re.fullmatch(r"[A-Za-z0-9_-][A-Za-z0-9_ -]{0,29}(?:\.gob)?", episode, re.I) and
            len(episode) < 32 and re.fullmatch(r"[A-Za-z0-9_-][A-Za-z0-9_. -]{0,25}\.jkl", level, re.I)):
        return "unsupported episode or map name"
    if episode.casefold().removesuffix(".gob") == "jk1mpdem":
        return "demo episode"
    return ""


def select_room(games, args):
    if not 0 < args.room_id < 10**9:
        raise ValueError("A positive, exact lobby room ID is required (maximum nine digits).")
    choices = [g for g in games if isinstance(g, dict) and type(g.get("id")) is int and g["id"] == args.room_id]
    if len(choices) != 1:
        raise ValueError("Selected room is absent or ambiguous on this relay.")
    game = choices[0]
    reason = unsupported(game, getattr(args, "allow_mod", False))
    if reason:
        raise ValueError("Selected room is unavailable: "+reason)
    episode = game["episode"]
    stem = episode[:-4] if episode.lower().endswith(".gob") else episode
    archive = args.episode_gob or game_file(args.data, "episode/"+stem+".gob")
    if not archive.is_file() or archive.name.casefold() != (stem+".gob").casefold():
        raise ValueError("The locally supplied GOB must match the selected episode name.")
    required = ("jkl/"+game["map"]).casefold()
    if not any(row["name"].casefold() == required and row["size"] > 0 for row in archive_index(archive)):
        raise ValueError("The local episode does not contain the advertised JKL.")
    if stem.casefold() == "jk1mp":
        if not archive.samefile(game_file(args.data, "episode/JK1MP.gob")):
            raise ValueError("Use the installed JK1MP for this stock episode.")
        archive = None
    return SelectedRoom(args.relay, args.room_id, episode, game["map"], args.seat, archive)


async def run(args):
    games = await list_games(args.relay)
    if args.command == "list":
        for game in games:
            if isinstance(game, dict):
                print(json.dumps({**{k:game.get(k) for k in ("id","name","episode","map","players","max","net")},
                                  "unavailable":unsupported(game) or None}, ensure_ascii=True))
        if not games:
            print("No WSRelay rooms are currently listed.")
        return
    room = select_room(games, args)
    runtime = args.runtime / ("selected-room-"+time.strftime("%Y%m%d-%H%M%S")+"-"+secrets.token_hex(4))
    mode = "ff-sabers" if args.sabers_only else "ff-guns"
    host = Host(args.data, args.engine_dir, runtime, str(room.room_id), None, False, mode,
                adaptive_lily=args.adaptive_lily, external=room)
    runner = web.AppRunner(host.app(), access_log=None, shutdown_timeout=1.)
    try:
        await runner.setup()
        await web.TCPSite(runner, "127.0.0.1", 0).start()
        host.set_port(runner.addresses[0][1])
        print(json.dumps({"page":host.url+"/bot/"+room.seat,
                          "credential":str((host.secrets_dir/(room.seat+".json")).resolve()),
                          "run":str((runtime/"run.json").resolve()), "room":room.public()}), flush=True)
        while True:
            host.hub.pump()
            host.expire_capture()
            await asyncio.sleep(.05)
    finally:
        await runner.cleanup()
        host.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    listing = commands.add_parser("list", help="Print advertised room IDs and availability, then disconnect.")
    join = commands.add_parser("join", help="Prepare one local bot page for the selected game.")
    for command in (listing, join):
        command.add_argument("--relay", default=ZONE_RELAY)
    join.add_argument("--room-id", type=int, required=True)
    join.add_argument("--data", type=Path, required=True)
    join.add_argument("--runtime", type=Path, required=True)
    join.add_argument("--engine-dir", type=Path, default=HERE.parent/"bin/bots-jkweb")
    join.add_argument("--episode-gob", type=Path, help="Locally owned episode containing the advertised map.")
    join.add_argument("--seat", choices=tuple(ROOM_PLAYERS), default="lily")
    join.add_argument("--sabers-only", action="store_true", help="Restrict this bot's weapon choices.")
    join.add_argument("--adaptive-lily", action="store_true", help="Enable the existing experimental Lily controls.")
    args = parser.parse_args(argv)
    try:
        if getattr(args,"adaptive_lily",False) and args.seat != "lily":
            parser.error("--adaptive-lily requires --seat lily.")
        asyncio.run(run(args))
    except (OSError, ValueError, TimeoutError, binascii.Error) as exc:
        parser.exit(1, f"{exc}\n")
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
